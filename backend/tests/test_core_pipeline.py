import copy
import random
from types import SimpleNamespace

import httpx
import pytest

from backend.app.core.config import get_config
from backend.app.defense.canary import get_session_canary
from backend.app.defense.hardening import build_messages
from backend.app.defense.output_check import OutputChecker, longest_common_substring
from backend.app.llm import target as target_module
from backend.app.llm.target import TargetError, TargetLLM
from backend.app.schemas import DetectionResult, LayerResult
from backend.app.services.pipeline import PipelineService


@pytest.fixture(autouse=True)
def local_tokenizer_stub(monkeypatch):
    """Unit tests do not require model files; retain the actual budget guard."""
    original = TargetLLM._load_tokenizer
    class FakeTokenizer:
        def apply_chat_template(self, messages, **kwargs):
            assert kwargs == {"tokenize": True, "add_generation_prompt": True, "enable_thinking": False}
            return list(range(20))
    monkeypatch.setattr(TargetLLM, "_load_tokenizer", lambda _self: FakeTokenizer())
    return original


def fast_config():
    config = get_config()
    for name in ("l1", "l2", "l3"):
        config["layers"][name]["enabled"] = False
    return config


def test_lcs_matches_exhaustive_reference_with_random_unicode():
    def reference(a, b):
        return max([len(a[i:j]) for i in range(len(a)) for j in range(i + 1, len(a) + 1) if a[i:j] in b] or [0])
    rng = random.Random(42)
    for _ in range(100):
        a = "".join(rng.choices("ab中文c", k=20))
        b = "".join(rng.choices("ab中文c", k=16))
        assert longest_common_substring(a, b) == reference(a, b)
    assert longest_common_substring("", "test") == 0
    assert longest_common_substring("a" * 30000, "b" * 20000) == 0


def test_prompt_hardening_random_delimiters_and_sandwich_preserves_original_task():
    config = get_config()
    first = build_messages("some data", config, "SENTINEL-test-secret-8219", "客观摘要")
    second = build_messages("some data", config, "SENTINEL-test-secret-8219", "客观摘要")
    assert first.messages[0]["role"] == "system"
    assert first.messages[1]["role"] == "user"
    assert first.messages != second.messages
    assert "some data" in first.messages[1]["content"]
    assert "再次确认原始任务：客观摘要" in first.messages[1]["content"]
    assert first.result.details["spotlighting"] and first.result.details["sandwich"]
    assert "SENTINEL-test-secret-8219" not in first.result.model_dump_json()
    baseline = build_messages("some data", config, "secret", enabled=False)
    assert baseline.messages[1]["content"] == "some data" and "secret" in baseline.system_prompt
    assert baseline.result.status == "disabled"


def test_canary_stable_per_session_unique_between_sessions():
    assert get_session_canary("unit-session-1") == get_session_canary("unit-session-1")
    assert get_session_canary("unit-session-1") != get_session_canary("unit-session-2")


def test_output_checks_canary_and_contiguous_prompt_leakage():
    checker = OutputChecker(get_config())
    result = checker.check("reply SECRET marker", "system", "SECRET")
    assert result.is_attack and result.details["canary_leaked"]
    assert "SECRET" not in result.model_dump_json()
    result = checker.check("x" + "s" * 61 + "z", "s" * 100, "different")
    assert result.is_attack and result.details["longest_common_substring"] == 61
    result = checker.check("s" * 60, "s" * 100, "different")
    assert not result.is_attack  # specified threshold is exceeded, not met


def test_response_guard_errors_are_explicit_and_unsafe_is_blocked():
    config = get_config()
    config["layers"]["l5"]["guard_response"] = True
    guard = SimpleNamespace(moderate_response=lambda prompt, response: LayerResult(layer="L3", is_attack=True, score=1, categories=["Unethical Acts"], details={"safety": "Unsafe", "refusal": "No"}))
    result = OutputChecker(config, guard).check("answer", "system", "secret", prompt="question")
    assert result.is_attack and result.details["moderation"]["safety"] == "Unsafe"
    guard.moderate_response = lambda *args: LayerResult(layer="L3", status="error", error="offline")
    result = OutputChecker(config, guard).check("answer", "system", "secret")
    assert result.status == "error" and result.is_attack is None


def test_pipeline_stops_before_target_on_detection_attack():
    service = PipelineService(fast_config())
    called = []
    service.target.generate = lambda _: called.append(True) or "should not run"
    result = service.process("attack", detection=DetectionResult(is_attack=True, strategy="any"))
    assert result.blocked and not called


def test_pipeline_baseline_canary_oracle_redaction_and_protected_block():
    service = PipelineService(fast_config())
    session_id = "canary-pipeline-test"
    secret = service.get_canary(session_id)
    service.target.generate = lambda messages: "leaked: " + secret
    baseline = service.process("request", protected=False, session_id=session_id)
    assert not baseline.blocked and baseline.output_check.details["canary_leaked"]
    assert baseline.output_check.status == "disabled"
    assert secret not in baseline.model_dump_json()
    guarded = service.process("request", protected=True, session_id=session_id)
    assert guarded.blocked and guarded.output_check.details["canary_leaked"]
    assert secret not in guarded.model_dump_json()
    service.config["layers"]["l5"]["enabled"] = False
    disabled = service.process("request", session_id=session_id)
    assert not disabled.blocked and disabled.output_check.details["canary_leaked"]
    assert secret not in disabled.model_dump_json()


def test_pipeline_target_failure_is_error_and_no_invented_reply():
    service = PipelineService(fast_config())
    def fail(_):
        raise TargetError("目标模型服务不可用")
    service.target.generate = fail
    result = service.process("question")
    assert result.error == "目标模型服务不可用" and result.output_check is None
    assert not result.blocked


def test_pipeline_output_guard_error_obeys_fail_closed():
    config = fast_config()
    config["layers"]["l5"]["guard_response"] = True
    service = PipelineService(config)
    service.target.generate = lambda _: "ordinary answer"
    service.guard.moderate_response = lambda *args: LayerResult(layer="L3", status="error", error="guard missing")
    assert service.process("question").blocked
    service.config["fusion"]["fail_closed"] = False
    result = service.process("question")
    assert not result.blocked and result.error == "guard missing"


def test_ollama_real_payload_disables_thinking_and_supports_low_ram(monkeypatch):
    config = get_config()
    monkeypatch.setattr(target_module.psutil, "virtual_memory", lambda: SimpleNamespace(total=8 * 1024 ** 3))
    seen = []
    def handler(request):
        import json
        seen.append(json.loads(request.content))
        assert request.url.path == "/api/chat"
        return httpx.Response(200, json={"message": {"content": "actual service reply"}})
    target = TargetLLM(config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert target.generate([{"role": "user", "content": "hello"}]) == "actual service reply"
    assert seen[0]["model"] == "qwen3:0.6b" and seen[0]["think"] is False
    assert seen[0]["stream"] is False and seen[0]["options"]["num_predict"] == 192


def test_openai_adapter_reads_key_from_environment_and_keeps_v1_path(monkeypatch):
    config = get_config()
    config["target"].update(provider="openai", base_url="http://127.0.0.1:9999/v1", model="local-model")
    monkeypatch.setenv("TARGET_API_KEY", "test-secret")
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-secret"
        return httpx.Response(200, json={"choices": [{"message": {"content": "reply"}}]})
    target = TargetLLM(config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert target.generate([{"role": "user", "content": "hello"}]) == "reply"


def test_cpu_mode_disables_ollama_gpu_layers():
    config = get_config()
    config["models"]["device"] = "cpu"
    def handler(request):
        import json
        body = json.loads(request.content)
        assert body["options"]["num_gpu"] == 0
        assert body["options"]["num_thread"] == config["models"]["cpu_threads"]
        return httpx.Response(200, json={"message": {"content": "CPU reply"}})
    target = TargetLLM(config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert target.generate([{"role": "user", "content": "hello"}]) == "CPU reply"


@pytest.mark.parametrize("ram,expected", [(16 * 1024 ** 3 - 1, "qwen3:0.6b"), (16 * 1024 ** 3, "qwen3:1.7b"), (32 * 1024 ** 3, "qwen3:1.7b")])
def test_low_ram_model_selection_at_exact_16_gib_boundary(monkeypatch, ram, expected):
    monkeypatch.setattr(target_module.psutil, "virtual_memory", lambda: SimpleNamespace(total=ram))
    assert TargetLLM(get_config()).model == expected


def test_oversized_prompt_rejected_before_any_network_call():
    config = get_config()
    config["target"].update(context_length=100, max_tokens=81)
    calls = []
    target = TargetLLM(config, client=httpx.Client(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(500))))
    with pytest.raises(TargetError, match="超过目标模型"):
        target.generate([{"role": "user", "content": "oversized"}])
    assert not calls
    target.settings["max_tokens"] = 80
    assert target.validate_context([{"role": "user", "content": "exact boundary"}]) == 20


def test_target_tokenizer_loading_is_local_only(tmp_path, monkeypatch, local_tokenizer_stub):
    import transformers
    config = get_config()
    config["models"]["target"]["path"] = str(tmp_path)
    config["models"]["target"]["small_path"] = str(tmp_path)
    (tmp_path / "tokenizer_config.json").write_text("{}")
    seen = []
    marker = object()
    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", lambda path, **kwargs: seen.append((path, kwargs)) or marker)
    target = TargetLLM(config)
    assert local_tokenizer_stub(target) is marker
    assert seen[0][1] == {"local_files_only": True, "trust_remote_code": False}


def test_missing_target_tokenizer_is_explicit_error(tmp_path, local_tokenizer_stub):
    config = get_config()
    config["models"]["target"].update(path=str(tmp_path), small_path=str(tmp_path))
    with pytest.raises(TargetError, match="tokenizer 未安装"):
        local_tokenizer_stub(TargetLLM(config))


def test_target_errors_do_not_echo_response_body_or_credentials():
    config = get_config()
    def handler(request):
        return httpx.Response(500, json={"error": "SECRET SHOULD NEVER APPEAR"})
    target = TargetLLM(config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(TargetError) as caught:
        target.generate([{"role": "user", "content": "hello"}])
    assert "500" in str(caught.value) and "SECRET" not in str(caught.value)


def test_production_ollama_uses_official_sdk_with_disabled_thinking(monkeypatch):
    received = []
    class FakeOfficialClient:
        def __init__(self, **kwargs):
            received.append(kwargs)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def chat(self, **kwargs):
            received.append(kwargs)
            return {"message": {"content": "SDK reply"}}
    monkeypatch.setattr(target_module.ollama, "Client", FakeOfficialClient)
    target = TargetLLM(get_config())
    assert target.generate([{"role": "user", "content": "hello"}]) == "SDK reply"
    assert received[0]["host"] == get_config()["target"]["base_url"]
    assert received[1]["think"] is False and received[1]["stream"] is False
