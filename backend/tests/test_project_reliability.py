"""Deployment recovery, invalid settings and bounded evaluation history."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.core.config import get_config, validate_config
from backend.app.db.models import EvaluationJob
from backend.tests.test_api import api


@pytest.mark.parametrize("value", [None, 12, False, [], {}])
def test_system_prompt_rejects_non_text_before_saving(value):
    config = copy.deepcopy(get_config())
    config["target"]["system_prompt"] = value
    with pytest.raises(ValueError, match="系统提示词"):
        validate_config(config)


@pytest.mark.parametrize("path", [
    ("layers", "l2", "max_tokens"), ("layers", "l2", "stride"),
    ("target", "max_tokens"), ("models", "cpu_threads"),
    ("app", "port"), ("app", "frontend_port"),
])
def test_runtime_integer_settings_reject_fractional_values(path):
    config = copy.deepcopy(get_config())
    section = config
    for key in path[:-1]:
        section = section[key]
    section[path[-1]] = {"port": 8000.5, "frontend_port": 5173.5, "cpu_threads": 2.5}.get(path[-1], 16.5)
    with pytest.raises(ValueError):
        validate_config(config)


def seed_jobs(sessions):
    with sessions() as db:
        for index in range(62):
            db.add(EvaluationJob(
                id=f"{index:032x}", user_id=1 if index < 60 else 2,
                experiment="detection", status="completed", progress=100,
                config={"proof": "private-config"}, result={"tables": {}, "proof": "Z" * 10000},
                archived=index == 0,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index),
            ))
        db.commit()


def test_history_pagination_is_lightweight_and_keeps_detail(api):
    client, admin, _, sessions = api
    seed_jobs(sessions)
    response = client.get("/api/eval/jobs", headers=admin, params={"summary": True, "page": 3, "page_size": 20})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 61 and data["page"] == 3 and data["page_size"] == 20
    assert len(data["items"]) == 20
    assert data["items"][0]["id"] == f"{21:032x}"
    assert all(row["has_result"] and row["result"] is None for row in data["items"])
    assert "private-config" not in response.text and "ZZZZ" not in response.text
    detail = client.get(f'/api/eval/jobs/{data["items"][0]["id"]}', headers=admin).json()
    assert detail["result"]["proof"] == "Z" * 10000
    assert len(response.content) < 20000


def test_history_pagination_preserves_ownership_and_archive_filters(api):
    client, admin, user, sessions = api
    seed_jobs(sessions)
    own = client.get("/api/eval/jobs", headers=user, params={"summary": True, "page_size": 1}).json()
    assert own["total"] == 2 and len(own["items"]) == 1
    assert own["items"][0]["id"] == f"{61:032x}"
    assert client.get(f'/api/eval/jobs/{1:032x}', headers=user).status_code == 404
    archived = client.get("/api/eval/jobs", headers=admin, params={"summary": True, "archived": True}).json()
    assert archived["total"] == 1 and archived["items"][0]["id"] == "0" * 32


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}])
def test_history_rejects_unbounded_pages(api, params):
    client, admin, _, _ = api
    assert client.get("/api/eval/jobs", headers=admin, params=params).status_code == 422


def test_history_does_not_treat_json_null_as_an_available_result(api):
    client, admin, _, sessions = api
    with sessions() as db:
        db.add(EvaluationJob(id="no-result", user_id=1, experiment="detection", status="cancelled", config={}, result=None))
        db.commit()
    item = client.get("/api/eval/jobs", headers=admin, params={"summary": True}).json()["items"][0]
    assert item["has_result"] is False and item["result"] is None
