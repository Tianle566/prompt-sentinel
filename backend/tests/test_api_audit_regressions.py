"""Isolated regressions for review items 2, 7, 8, 10 and 12; no model calls."""
import json
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import bcrypt
import pytest
from sqlalchemy import event, select

from backend.tests.test_api import api
from backend.app.api import routes
from backend.app.db.models import EvaluationJob, RequestLog, User


@pytest.fixture
def isolated_api(api, monkeypatch, tmp_path):
    routes._login_attempts.clear()
    monkeypatch.setattr(routes, "ROOT", tmp_path)
    active = threading.Event()
    monkeypatch.setattr(routes, "_evaluation_running", active, raising=False)
    detection = dict(is_attack=False, layer_results=[], latency_ms=0, reliable=True, strategy="any")
    monkeypatch.setattr(routes, "_detection", lambda *args: SimpleNamespace(detect=lambda text: detection, guard=None))
    monkeypatch.setattr(routes, "_pipeline", lambda *args: SimpleNamespace(process=lambda *a, **kw: dict(output="synthetic test reply", blocked=False, detection=detection, latency_ms=0, error=None, session_id="fixture")))
    yield api
    routes._login_attempts.clear()


def test_detect_returns_503_within_five_second_lock_deadline(isolated_api, monkeypatch):
    client, _, headers, _ = isolated_api
    lock = threading.Lock()
    lock.acquire()
    monkeypatch.setattr(routes, "_inference_lock", lock)
    routes._evaluation_running.set()
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(client.post, "/api/detect", headers=headers, json={"text": "benign fixture"})
        try:
            response = future.result(timeout=6)
            assert response.status_code == 503
            assert response.json()["detail"] == "评测任务运行中，请稍后重试"
            assert time.monotonic() - started < 6
        finally:
            lock.release()
            routes._evaluation_running.clear()


@pytest.mark.parametrize("path", ["/api/detect", "/api/chat", "/api/document/summarize", "/api/attack/run"])
def test_protected_routes_use_bounded_acquisition_during_evaluation(isolated_api, monkeypatch, path):
    client, _, headers, _ = isolated_api
    deadlines = []
    class BusyLock:
        def acquire(self, blocking=True, timeout=-1):
            deadlines.append(timeout)
            return False
        def __enter__(self):
            raise AssertionError("Unbounded global-lock acquisition")
        def release(self):
            raise AssertionError("Unacquired lock must not be released")
    monkeypatch.setattr(routes, "_inference_lock", BusyLock())
    routes._evaluation_running.set()
    kwargs = {"json": {"text": "benign fixture"}}
    if path.endswith("summarize"):
        kwargs = {"files": {"file": ("test.txt", b"benign fixture", "text/plain")}}
    elif path.endswith("run"):
        kwargs = {"json": {"texts": ["PWNED-TEST"], "protected": True}}
    try:
        response = client.post(path, headers=headers, **kwargs)
        assert response.status_code == 503
        assert deadlines == [5]
    finally:
        routes._evaluation_running.clear()


@pytest.mark.parametrize("raises", [False, True])
def test_evaluation_releases_global_lock_and_clears_running_state(isolated_api, monkeypatch, raises):
    _, _, _, sessions = isolated_api
    with sessions() as db:
        db.add(EvaluationJob(id="fixture-job", user_id=1, experiment="detection", config={}, status="queued"))
        db.commit()
    monkeypatch.setattr(routes, "SessionLocal", sessions)
    observed = []
    def probe():
        available = routes._inference_lock.acquire(blocking=False)
        if available:
            routes._inference_lock.release()
        return available
    def evaluate(**kwargs):
        with ThreadPoolExecutor(max_workers=1) as executor:
            observed.append((executor.submit(probe).result(timeout=1), routes._evaluation_running.is_set()))
        if raises:
            raise RuntimeError("Synthetic evaluation failure")
        return {"status": "completed"}
    monkeypatch.setattr("scripts.run_eval.run_evaluation", evaluate)
    routes._execute_job("fixture-job", routes.get_config(), routes.EvalBody(experiment="detection"))
    assert observed == [(True, True)]
    assert not routes._evaluation_running.is_set()
    with sessions() as db:
        assert db.get(EvaluationJob, "fixture-job").status == ("failed" if raises else "completed")


@pytest.mark.parametrize("password", ["not-a-real-password", "密" * 30])
def test_unknown_login_always_checks_precomputed_bcrypt_hash(isolated_api, monkeypatch, password):
    client, _, _, _ = isolated_api
    calls = []
    check = bcrypt.checkpw
    def observed(candidate, hashed):
        calls.append(hashed)
        return check(candidate, hashed)
    monkeypatch.setattr(routes.bcrypt, "checkpw", observed)
    response = client.post("/api/auth/login", json={"username": "absent-user", "password": password})
    assert response.status_code == 401
    assert len(calls) == 1
    assert calls[0].startswith((b"$2b$12$", b"$2a$12$"))


def test_login_rate_limit_isolated_by_username(isolated_api, monkeypatch):
    client, _, _, _ = isolated_api
    monkeypatch.setattr(routes.bcrypt, "checkpw", lambda *args: False)
    for _ in range(15):
        assert client.post("/api/auth/login", json={"username": "first-user", "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "first-user", "password": "wrong"}).status_code == 429
    assert client.post("/api/auth/login", json={"username": "second-user", "password": "wrong"}).status_code == 401


@pytest.mark.parametrize("password", ["new-pass", "N" * 72, "密码新"])
def test_password_change_invalidates_old_password_and_removes_bootstrap_entry(isolated_api, password):
    client, _, headers, sessions = isolated_api
    path = routes.ROOT / ".runtime" / "credentials.json"
    path.parent.mkdir()
    other = {"username": "test-admin", "password": "admin-test-password"}
    path.write_text(json.dumps({"admin": other, "user": {"username": "test-user", "password": "user-test-password"}}))
    response = client.post("/api/auth/password", headers=headers, json={"old_password": "user-test-password", "new_password": password})
    assert response.status_code == 200
    assert json.loads(path.read_text()) == {"admin": other}
    assert path.stat().st_mode & 0o777 == 0o600
    with sessions() as db:
        user = db.scalar(select(User).where(User.username == "test-user"))
        assert bcrypt.checkpw(password.encode(), user.password_hash.encode())
    assert client.post("/api/auth/login", json={"username": "test-user", "password": "user-test-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "test-user", "password": password}).status_code == 200


@pytest.mark.parametrize("password", ["a" * 7, "a" * 73, "密" * 25])
def test_password_change_rejects_invalid_utf8_byte_lengths(isolated_api, password):
    client, _, headers, sessions = isolated_api
    with sessions() as db:
        before = db.get(User, 2).password_hash
    response = client.post("/api/auth/password", headers=headers, json={"old_password": "user-test-password", "new_password": password})
    assert response.status_code == 422
    with sessions() as db:
        assert db.get(User, 2).password_hash == before


def test_password_change_requires_login_and_correct_old_password(isolated_api):
    client, _, headers, sessions = isolated_api
    body = {"old_password": "wrong", "new_password": "valid-new-password"}
    assert client.post("/api/auth/password", json=body).status_code == 401
    with sessions() as db:
        before = db.get(User, 2).password_hash
    assert client.post("/api/auth/password", headers=headers, json=body).status_code == 400
    with sessions() as db:
        assert db.get(User, 2).password_hash == before


@pytest.mark.parametrize("protected,expected", [(False, 400), (True, 200)])
def test_unprotected_chat_rejects_remote_target_before_generation(isolated_api, monkeypatch, protected, expected):
    client, _, headers, _ = isolated_api
    config = routes.get_config()
    config["target"].update(provider="openai", base_url="https://third-party.example/v1")
    monkeypatch.setattr(routes, "get_config", lambda: config)
    response = client.post("/api/chat", headers=headers, json={"text": "test", "protected": protected})
    assert response.status_code == expected


def test_stats_aggregates_history_but_bounds_latency_to_latest_1000(isolated_api):
    client, _, headers, sessions = isolated_api
    older = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with sessions() as db:
        for i in range(1005):
            old = i < 5
            layer = "L1" if old else "L2"
            db.add(RequestLog(user_id=2, kind="chat", text="synthetic fixture", protected=True, blocked=old, attack_type="attack" if old else "benign", hit_layers=[layer], latency_ms=10 if old else 1, created_at=older if old else older+timedelta(days=1), result={"detection": {"layer_results": [{"layer": layer, "status": "ok", "enabled": True, "latency_ms": 999 if old else 2}]}}))
        db.add(RequestLog(user_id=1, kind="chat", text="other user", protected=True, blocked=True, attack_type="other-user", hit_layers=["L5"], latency_ms=10000, result={}))
        db.commit()
    hydrated = []
    def loaded(instance, context):
        hydrated.append(instance.id)
    event.listen(RequestLog, "load", loaded)
    try:
        response = client.get("/api/stats", headers=headers)
    finally:
        event.remove(RequestLog, "load", loaded)
    assert response.status_code == 200
    value = response.json()
    assert value["total_requests"] == 1005 and value["blocked_requests"] == 5
    assert value["average_latency_ms"] == pytest.approx(1050 / 1005)
    assert value["daily"] == [{"date": "2026-01-01", "total": 5, "blocked": 5}, {"date": "2026-01-02", "total": 1000, "blocked": 0}]
    assert value["attack_types"] == [{"name": "attack", "value": 5}]
    assert {row["name"]: row["value"] for row in value["layers"]} == {"L1": 5, "L2": 1000, "L3": 0, "L5": 0}
    assert value["latencies"] == [{"name": "L2", "value": 2}]
    assert len(hydrated) <= 1000


def test_eval_request_schema_has_no_unused_dataset_selector():
    assert "dataset" not in routes.EvalBody.model_json_schema()["properties"]


def test_frontend_evaluation_request_does_not_send_dataset():
    node = shutil.which("node")
    assert node, "Node.js is required to verify the frontend request contract"
    source = (Path(__file__).parents[2] / "frontend/src/pages/Evaluation.vue").read_text()
    create = source.split("async function create()", 1)[1].split("function setDataset()", 1)[0]
    js = """const form={dataset:'detect',experiment:'detection',limit:4,asr_limit:2};
const creating={value:false},error={value:''},custom={value:false},config={value:null},active={value:null};
const ElMessage={success(){}},errorText=String;let payload;const api={async post(path,body){payload=body;return {data:{id:'fixture'}}}};async function refresh(){}
async function create()""" + create + "\nawait create();console.log(JSON.stringify(payload));"
    result = subprocess.run([node, "--input-type=module", "-e", js], capture_output=True, text=True, timeout=5, check=True)
    assert json.loads(result.stdout) == {"experiment": "detection", "limit": 4, "asr_limit": 2}
