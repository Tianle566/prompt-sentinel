"""Operational views must agree on status, time range, export and user scope."""
import csv
import io
from datetime import datetime

import pytest
from types import SimpleNamespace

from backend.app.api import routes
from backend.app.db.models import RequestLog
from backend.tests.test_api import api


def add_log(sessions, **changes):
    values = dict(user_id=2, kind="chat", text="季度预算 100%_approved", protected=True,
                  blocked=False, attack_type="benign", hit_layers=[], latency_ms=25,
                  result={}, created_at=datetime(2026, 10, 28, 12))
    values.update(changes)
    with sessions() as db:
        row = RequestLog(**values)
        db.add(row)
        db.commit()
        return row.id


@pytest.mark.parametrize("result,blocked", [
    ({"error": "target unavailable"}, False),
    ({"detection": {"reliable": False}}, True),
    ({"output_check": {"status": "error"}}, False),
    ({"hardening": {"status": "error"}}, False),
])
def test_execution_errors_are_never_presented_as_success(api, result, blocked):
    client, admin, user, sessions = api
    log_id = add_log(sessions, result=result, blocked=blocked)
    add_log(sessions, text="healthy allowed")
    add_log(sessions, text="healthy blocked", blocked=True)
    errors = client.get("/api/logs", headers=user, params={"status": "error"}).json()
    assert [row["id"] for row in errors["items"]] == [log_id]
    assert errors["items"][0]["status"] == "error"
    assert client.get(f"/api/logs/{log_id}", headers=user).json()["status"] == "error"
    assert client.get("/api/logs?status=allowed", headers=user).json()["total"] == 1
    assert client.get("/api/logs?status=blocked", headers=user).json()["total"] == 1
    stats = client.get("/api/stats", headers=user).json()
    assert stats["error_requests"] == 1
    assert next(row for row in stats["recent_requests"] if row["id"] == log_id)["status"] == "error"
    exported = client.get("/api/logs/export.csv?status=error", headers=user)
    records = list(csv.reader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert len(records) == 2 and records[1][-1] == "error"


def test_search_uses_literal_text_and_keeps_export_and_user_scope(api):
    client, admin, user, sessions = api
    expected = add_log(sessions, kind="attack", blocked=True)
    add_log(sessions, text="季度预算 100anything-approved", kind="attack", blocked=True)
    add_log(sessions, user_id=1, kind="attack", blocked=True)
    add_log(sessions, kind="document", blocked=True)
    params = {"q": "%_", "kind": "attack", "status": "blocked"}
    listing = client.get("/api/logs", headers=user, params=params).json()
    assert [row["id"] for row in listing["items"]] == [expected]
    exported = client.get("/api/logs/export.csv", headers=user, params=params)
    records = list(csv.reader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert len(records) == 2 and int(records[1][0]) == expected
    assert client.get("/api/logs", headers=user, params={"q": f"#{expected}"}).json()["total"] == 1
    assert client.get("/api/logs", headers=user, params={**params, "user_id": 1}).status_code == 403


def test_time_range_normalizes_offsets_for_every_view(api):
    client, admin, user, sessions = api
    expected = add_log(sessions, created_at=datetime(2026, 10, 28, 15, 30), blocked=True,
                       hit_layers=["L1"], kind="attack", attack_type="goal_hijacking",
                       result={"detection": {"reliable": True}, "error": None,
                               "attack_evaluation": {"oracle": {"type": "marker", "marker": "OK"}, "success": False}})
    add_log(sessions, created_at=datetime(2026, 10, 28, 16, 30))
    add_log(sessions, created_at=datetime(2026, 10, 27, 15, 30))
    add_log(sessions, user_id=1, created_at=datetime(2026, 10, 28, 15, 30))
    params = {"start": "2026-10-28T23:00:00+08:00", "end": "2026-10-28T23:59:59+08:00"}
    listing = client.get("/api/logs", headers=user, params=params).json()
    assert [row["id"] for row in listing["items"]] == [expected]
    stats = client.get("/api/stats", headers=user, params=params).json()
    assert stats["total_requests"] == stats["blocked_requests"] == 1
    assert stats["attack_interception"]["evaluated"] == stats["attack_interception"]["intercepted"] == 1
    assert len(stats["daily"]) == 1
    assert next(row for row in stats["layers"] if row["name"] == "L1")["value"] == 1
    assert [row["id"] for row in stats["recent_requests"]] == [expected]
    exported = client.get("/api/logs/export.csv", headers=user, params=params)
    assert len(list(csv.reader(io.StringIO(exported.content.decode("utf-8-sig"))))) == 2


@pytest.mark.parametrize("path", ["/api/logs", "/api/stats", "/api/logs/export.csv"])
def test_reversed_time_ranges_are_rejected(api, path):
    client, admin, user, sessions = api
    response = client.get(path, headers=user, params={"start": "2026-10-29T00:00:00Z", "end": "2026-10-28T00:00:00Z"})
    assert response.status_code == 422


@pytest.mark.parametrize("params", [{"status": "unknown"}, {"kind": "admin"}, {"q": "x" * 301}])
def test_invalid_log_filters_are_rejected(api, params):
    client, admin, user, sessions = api
    assert client.get("/api/logs", headers=user, params=params).status_code == 422
    assert client.get("/api/logs/export.csv", headers=user, params=params).status_code == 422


def test_blocked_outcome_filter_includes_fail_closed_errors(api):
    client, admin, user, sessions = api
    failed = add_log(sessions, blocked=True, result={"detection": {"reliable": False}})
    blocked = add_log(sessions, blocked=True)
    add_log(sessions)
    rows = client.get("/api/logs?blocked=true", headers=user).json()
    assert {row["id"] for row in rows["items"]} == {failed, blocked}
    assert {row["status"] for row in rows["items"]} == {"error", "blocked"}
    assert client.get("/api/stats", headers=user).json()["blocked_requests"] == rows["total"]


def test_exact_sample_lookup_is_not_limited_to_first_page(api, monkeypatch):
    client, admin, user, sessions = api
    monkeypatch.setattr(routes, "_samples", lambda: [{"id": f"sample-{i}", "text": "test", "attack_type": "goal_hijacking"} for i in range(220)])
    response = client.get("/api/attack/samples", headers=user, params={"sample_id": "sample-219", "limit": 1})
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "sample-219"
    assert client.get("/api/attack/samples?sample_id=missing", headers=user).status_code == 404


def test_detection_response_links_to_the_saved_request(api, monkeypatch):
    client, admin, user, sessions = api
    result = {"is_attack": False, "latency_ms": 12, "reliable": True, "layer_results": []}
    monkeypatch.setattr(routes, "_detection", lambda: SimpleNamespace(detect=lambda text: result.copy()))
    response = client.post("/api/detect", headers=user, json={"text": "normal request"}).json()
    detail = client.get(f"/api/logs/{response['id']}", headers=user).json()
    assert detail["kind"] == "detect" and detail["text"] == "normal request"
    assert detail["result"]["detection"]["is_attack"] is False
