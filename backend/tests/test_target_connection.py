"""Credential isolation, endpoint binding and the OpenAI wire contract."""
import json

import httpx
import pytest
from sqlalchemy import select

from backend.app.api import target_connection
from backend.app.core import config as configuration
from backend.app.core.target_credentials import credential_for, credential_path, normalize_base_url
from backend.app.db.models import AdminAudit, PolicyAudit
from backend.app.llm.target import TargetError, TargetLLM
from backend.tests.test_api import api

KEY = "unit-only-target-credential-7384"


@pytest.fixture
def connection_api(api, monkeypatch):
    monkeypatch.delenv("TARGET_API_KEY", raising=False)
    return api


def body(**updates):
    return {"provider": "openai", "base_url": "https://compatible.example/v1", "model": "chat-model", **updates}


def test_saved_key_is_private_persistent_and_used_by_actual_adapter(connection_api, monkeypatch):
    client, admin, user, sessions = connection_api
    response = client.put("/api/admin/target", headers=admin, json=body(api_key="Bearer " + KEY))
    assert response.status_code == 200
    assert response.json()["credential"] == {"configured": True, "source": "saved", "saved": True, "saved_base_url": "https://compatible.example/v1"}
    assert json.loads(credential_path().read_text())["api_key"] == KEY
    assert credential_path().parent == configuration.CONFIG_PATH.parent / ".runtime"
    monkeypatch.setenv("TARGET_API_KEY", "different-environment-key")

    def upstream(request):
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer " + KEY
        assert json.loads(request.content)["model"] == "chat-model"
        return httpx.Response(200, json={"choices": [{"message": {"content": "wire reply"}}]})

    target = TargetLLM(configuration.get_config(), client=httpx.Client(transport=httpx.MockTransport(upstream)))
    assert target.generate([{"role": "user", "content": "hello"}]) == "wire reply"
    assert "api_key" not in target.config["target"]
    for headers in (admin, user):
        assert KEY not in client.get("/api/config", headers=headers).text
    assert KEY not in client.get("/api/admin/target", headers=admin).text
    assert KEY not in client.get("/api/admin/audits", headers=admin).text
    assert KEY not in client.get("/api/admin/policy/history", headers=admin).text
    assert KEY not in configuration.CONFIG_PATH.read_text()
    with sessions() as db:
        assert KEY not in json.dumps(db.scalar(select(PolicyAudit)).after)
        assert db.scalar(select(AdminAudit)).action == "target.connection"


def test_blank_key_preserves_saved_key_and_clear_removes_it(connection_api):
    client, admin, _, _ = connection_api
    assert client.put("/api/admin/target", headers=admin, json=body(api_key=KEY)).status_code == 200
    changed = client.put("/api/admin/target", headers=admin, json=body(model="other-model", api_key=""))
    assert changed.status_code == 200 and changed.json()["credential"]["saved"]
    assert credential_for(configuration.get_config()["target"])[0] == KEY
    removed = client.put("/api/admin/target", headers=admin, json=body(clear_api_key=True))
    assert removed.status_code == 200 and not removed.json()["credential"]["configured"]
    assert not credential_path().exists()


def test_endpoint_binding_prevents_reusing_saved_key_at_other_address(connection_api):
    client, admin, _, _ = connection_api
    assert client.put("/api/admin/target", headers=admin, json=body(api_key=KEY)).status_code == 200
    original = configuration.get_config()["target"]
    changed = client.put("/api/admin/target", headers=admin, json=body(base_url="https://another.example/v1"))
    assert changed.status_code == 200 and not changed.json()["credential"]["configured"]
    assert credential_for(configuration.get_config()["target"])[0] == ""
    assert credential_for(original)[0] == KEY


def test_environment_remains_available_after_clearing_local_key(connection_api, monkeypatch):
    client, admin, _, _ = connection_api
    monkeypatch.setenv("TARGET_API_KEY", "environment-only-unit-key")
    assert client.put("/api/admin/target", headers=admin, json=body(api_key=KEY)).status_code == 200

    def request(self, method, path, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer environment-only-unit-key"
        return {"choices": [{"message": {"content": "environment reply"}}]}

    monkeypatch.setattr(TargetLLM, "_request", request)
    probe = client.post("/api/admin/target/test", headers=admin, json=body(clear_api_key=True))
    assert probe.status_code == 200 and probe.json()["ok"]
    assert json.loads(credential_path().read_text())["api_key"] == KEY
    response = client.put("/api/admin/target", headers=admin, json=body(clear_api_key=True))
    assert response.json()["credential"] == {"configured": True, "source": "environment", "saved": False, "saved_base_url": ""}


@pytest.mark.parametrize("url,expected", [
    ("https://API.Example:443", "https://api.example/v1"),
    ("https://api.example/v1/", "https://api.example/v1"),
    ("https://api.example/custom/v1/chat/completions", "https://api.example/custom/v1"),
    ("http://[::1]:8080/v1/models", "http://[::1]:8080/v1"),
])
def test_normalizes_openai_root_and_full_endpoint_urls(url, expected):
    assert normalize_base_url(url) == expected


@pytest.mark.parametrize("changes", [
    {"base_url": "file:///etc/passwd"},
    {"base_url": "https://user:password@compatible.example/v1"},
    {"base_url": "https://compatible.example/v1?api_key=" + KEY},
    {"base_url": "https://compatible.example/v1#" + KEY},
    {"base_url": "https://compatible.example:99999/v1"},
    {"base_url": "https://compatible.example/\n/v1"},
    {"api_key": KEY + "\ninvalid"},
    {"api_key": KEY + " 中文"},
    {"api_key": KEY, "clear_api_key": True},
    {"model": ""},
    {"api_key": KEY * 200},
    {"api_key": KEY, "provider": "ollama"},
    {"api_key": KEY, "unknown": KEY},
])
def test_invalid_imports_never_echo_or_persist_secrets(connection_api, changes):
    client, admin, _, _ = connection_api
    original = configuration.CONFIG_PATH.read_bytes()
    response = client.put("/api/admin/target", headers=admin, json=body(**changes))
    assert response.status_code == 422
    assert KEY not in response.text and '"input"' not in response.text
    assert configuration.CONFIG_PATH.read_bytes() == original
    assert not credential_path().exists()


@pytest.mark.parametrize("method,path,payload", [
    ("get", "/api/admin/target", None),
    ("put", "/api/admin/target", body(api_key=KEY)),
    ("post", "/api/admin/target/models", body(api_key=KEY)),
    ("post", "/api/admin/target/test", body(api_key=KEY)),
])
def test_only_administrators_can_access_connection_operations(connection_api, monkeypatch, method, path, payload):
    client, _, user, _ = connection_api
    monkeypatch.setattr(TargetLLM, "generate", lambda *_: pytest.fail("unauthorized upstream call"))
    monkeypatch.setattr(TargetLLM, "list_models", lambda *_: pytest.fail("unauthorized upstream call"))
    options = {"json": payload} if payload is not None else {}
    assert client.request(method, path, **options).status_code == 401
    assert client.request(method, path, headers=user, **options).status_code == 403
    assert not credential_path().exists()


def test_draft_model_list_and_test_do_not_save_configuration_or_key(connection_api, monkeypatch):
    client, admin, _, _ = connection_api
    original = configuration.CONFIG_PATH.read_bytes()
    calls = []
    real_request = TargetLLM._request

    def upstream(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer " + KEY
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "chat-model"}, {"id": KEY}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": KEY}}]})

    def request_with_transport(self, *args, **kwargs):
        self._client = httpx.Client(transport=httpx.MockTransport(upstream))
        return real_request(self, *args, **kwargs)

    monkeypatch.setattr(TargetLLM, "_request", request_with_transport)
    models = client.post("/api/admin/target/models", headers=admin, json=body(model="", api_key=KEY))
    assert models.status_code == 200 and models.json()["models"] == ["chat-model"]
    response = client.post("/api/admin/target/test", headers=admin, json=body(api_key=KEY))
    assert response.status_code == 200 and response.json()["ok"]
    assert KEY not in response.text
    assert json.loads(calls[-1].content)["messages"] == [{"role": "user", "content": "Reply with OK."}]
    assert configuration.CONFIG_PATH.read_bytes() == original and not credential_path().exists()


@pytest.mark.parametrize("code", [401, 403, 404, 429, 500])
def test_upstream_errors_are_sanitized_and_do_not_expire_console_login(connection_api, monkeypatch, code):
    client, admin, _, _ = connection_api

    def request(self, *args, **kwargs):
        response = httpx.Response(code, json={"error": {"message": KEY}}, request=httpx.Request("POST", "https://compatible.example/v1/chat/completions"))
        response.raise_for_status()

    monkeypatch.setattr(TargetLLM, "_request", request)
    response = client.post("/api/admin/target/test", headers=admin, json=body(api_key=KEY))
    assert response.status_code == 502 and str(code) in response.text and KEY not in response.text
    assert client.get("/api/auth/me", headers=admin).status_code == 200


def test_save_failure_restores_key_and_exact_config_file(connection_api, monkeypatch):
    client, admin, _, _ = connection_api
    assert client.put("/api/admin/target", headers=admin, json=body(api_key=KEY)).status_code == 200
    old_config, old_key = configuration.CONFIG_PATH.read_bytes(), credential_path().read_bytes()

    def fail(*args, **kwargs):
        raise OSError("private save failure")

    monkeypatch.setattr(target_connection, "audit", fail)
    response = client.put("/api/admin/target", headers=admin, json=body(api_key="replacement-unit-key"))
    assert response.status_code == 500
    assert configuration.CONFIG_PATH.read_bytes() == old_config and credential_path().read_bytes() == old_key


def test_compatibility_models_contract_and_safe_malformed_response(connection_api):
    config = configuration.get_config()
    config["target"].update(provider="openai", base_url="https://compatible.example")

    def upstream(request):
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": "invalid"})

    target = TargetLLM(config, client=httpx.Client(transport=httpx.MockTransport(upstream)))
    with pytest.raises(TargetError, match="不兼容的模型列表"):
        target.list_models()


def test_log_redaction_covers_saved_key_and_public_config_hides_inline_key(connection_api, monkeypatch):
    from backend.app.api import operations
    client, admin, _, _ = connection_api
    assert client.put("/api/admin/target", headers=admin, json=body(api_key=KEY)).status_code == 200
    root = configuration.CONFIG_PATH.parent
    monkeypatch.setattr(operations, "ROOT", root)
    (root / ".runtime/backend.log").write_text("debug " + KEY, encoding="utf-8")
    response = client.get("/api/admin/runtime/errors/backend", headers=admin)
    assert response.status_code == 200 and KEY not in response.text and "已隐藏" in response.json()["text"]
    config = configuration.get_config()
    config["target"]["api_key"] = KEY
    assert KEY not in json.dumps(configuration.public_config(config))
