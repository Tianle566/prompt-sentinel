"""Attack interception is distinct from traffic blocking and attack failure."""
import pytest

from backend.app.api import routes
from backend.app.db.models import RequestLog
from backend.tests.test_api import api


def outcome(blocked=False, success=False, oracle=None):
    return {
        "blocked": blocked, "error": None,
        "detection": {"reliable": True, "layer_results": []},
        "attack_evaluation": {
            "success": success,
            "oracle": oracle if oracle is not None else {"type": "marker", "marker": "RESULT-42"},
        },
    }


def add_record(db, result, **changes):
    values = dict(user_id=2, kind="attack", text="synthetic metric fixture", protected=True,
                  blocked=result["blocked"], attack_type="goal_hijacking", hit_layers=[], latency_ms=1, result=result)
    values.update(changes)
    db.add(RequestLog(**values))


def test_counts_only_reliable_protected_attack_tests_and_preserves_user_scope(api):
    client, admin, user, sessions = api
    valid = [outcome(True), outcome(True, oracle={"type": "canary"}), outcome(False, True), outcome(False, False)]
    failed_detection = outcome(True)
    failed_detection.update(error="detector failed", detection={"reliable": False})
    failed_target = outcome()
    failed_target["error"] = "target failed"
    failed_output = outcome(True)
    failed_output["output_check"] = {"status": "error"}
    no_oracle = outcome(True)
    no_oracle["attack_evaluation"]["oracle"] = None
    no_reliability = outcome(True)
    no_reliability["detection"] = {}
    unknown = [outcome(False, None), no_oracle, outcome(True, oracle={"type": "unsupported"}),
               outcome(True, oracle={"type": "marker", "marker": " "}), no_reliability, outcome(True, True)]
    with sessions() as db:
        for result in valid + [failed_detection, failed_target, failed_output] + unknown:
            add_record(db, result)
        add_record(db, outcome(True), protected=False)
        add_record(db, outcome(True), kind="chat")
        add_record(db, outcome(True), kind="document")
        add_record(db, outcome(True), attack_type="benign")
        add_record(db, outcome(True), user_id=1)
        db.commit()
    expected = {"total": 13, "evaluated": 4, "intercepted": 2, "not_intercepted": 2, "errors": 3, "unknown": 6, "rate": 0.5}
    response = client.get("/api/stats", headers=user)
    assert response.status_code == 200
    assert response.json()["attack_interception"] == expected
    global_stats = client.get("/api/stats", headers=admin).json()["attack_interception"]
    assert global_stats == dict(expected, total=14, evaluated=5, intercepted=3, rate=0.6)


def test_empty_or_unknown_only_data_has_no_percentage(api):
    client, _, user, sessions = api
    empty = client.get("/api/stats", headers=user).json()["attack_interception"]
    assert empty == {"total": 0, "evaluated": 0, "intercepted": 0, "not_intercepted": 0, "errors": 0, "unknown": 0, "rate": None}
    with sessions() as db:
        add_record(db, outcome(False, None))
        db.commit()
    value = client.get("/api/stats", headers=user).json()["attack_interception"]
    assert value["total"] == value["unknown"] == 1
    assert value["evaluated"] == value["intercepted"] == 0
    assert value["rate"] is None


def test_metric_uses_all_history_including_older_interceptions(api):
    client, _, user, sessions = api
    with sessions() as db:
        for index in range(1005):
            add_record(db, outcome(index < 5, index >= 5))
        db.commit()
    value = client.get("/api/stats", headers=user).json()["attack_interception"]
    assert value["evaluated"] == 1005 and value["intercepted"] == 5
    assert value["rate"] == pytest.approx(5 / 1005)


def test_batch_and_cumulative_metrics_share_the_same_definition(api, monkeypatch):
    client, _, user, _ = api

    def run(text, protected, **kwargs):
        result = outcome(blocked=text == "blocked" and protected)
        result.update(output="RESULT-42" if text == "successful attack" else "ordinary reply", latency_ms=1, session_id="fixture")
        if text == "error":
            result.update(blocked=True, error="model unavailable", detection={"reliable": False})
        return result

    monkeypatch.setattr(routes, "_run", run)
    body = {"texts": ["blocked", "successful attack", "model refusal", "error"], "protected": True,
            "attack_type": "goal_hijacking", "expected_marker": "RESULT-42"}
    response = client.post("/api/attack/run", headers=user, json=body)
    assert response.status_code == 200
    data = response.json()
    expected = {"total": 4, "evaluated": 3, "intercepted": 1, "not_intercepted": 2, "errors": 1, "unknown": 0, "rate": pytest.approx(1 / 3)}
    assert data["protected"] is True and data["attack_interception"] == expected
    assert client.get("/api/stats", headers=user).json()["attack_interception"] == expected
    baseline = client.post("/api/attack/run", headers=user, json=dict(body, texts=["successful attack"], protected=False)).json()
    assert baseline["protected"] is False and baseline["attack_interception"]["rate"] is None
    assert baseline["attack_interception"]["total"] == 0
    assert client.get("/api/stats", headers=user).json()["attack_interception"] == expected
