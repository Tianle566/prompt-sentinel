"""Configuration regressions use a private YAML file and an isolated API database."""
from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from packaging.requirements import Requirement
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api import routes
from backend.app.core import config as config_module
from backend.app.core.auth import create_token
from backend.app.db.models import Base, User
from backend.app.db.session import get_db


INTEGER_FIELDS = [
    (("layers", "l2", "batch_size"), 1, 64),
    (("layers", "l3", "max_tokens"), 256, 32768),
    (("layers", "l3", "max_new_tokens"), 8, 512),
    (("target", "context_length"), 512, 131072),
]
INVALID_VALUES = [
    (path, invalid)
    for path, low, high in INTEGER_FIELDS
    for invalid in (low - 1, high + 1, True, False, float(low), str(low), None)
] + [
    (("target", field), invalid)
    for field in ("model", "small_model")
    for invalid in ("", "  \t", "x" * 201, 7, True, None, [])
]


def _updates(path, value):
    updates = value
    for part in reversed(path):
        updates = {part: updates}
    return updates


@pytest.mark.parametrize("path,invalid", INVALID_VALUES)
def test_new_config_fields_reject_invalid_values(path, invalid):
    config = config_module.merge_dict(config_module.get_config(), _updates(path, invalid))
    with pytest.raises(ValueError):
        config_module.validate_config(config)


@pytest.mark.parametrize("path,low,high", INTEGER_FIELDS)
def test_new_integer_config_fields_accept_inclusive_bounds(path, low, high):
    for value in (low, high):
        config = config_module.merge_dict(config_module.get_config(), _updates(path, value))
        assert config_module.validate_config(config) == config


@pytest.mark.parametrize("invalid", [None, "http://localhost:5173", {}, [1], [None], ["http://localhost:5173", False]])
def test_cors_origins_requires_string_list(invalid):
    config = config_module.get_config()
    config["app"]["cors_origins"] = invalid
    with pytest.raises(ValueError):
        config_module.validate_config(config)


@pytest.mark.parametrize("value", [[], ["http://localhost:5173"], ["https://a.example", "https://b.example"]])
def test_cors_origins_accepts_string_lists(value):
    config = config_module.get_config()
    config["app"]["cors_origins"] = value
    assert config_module.validate_config(config) == config


@pytest.fixture
def config_api(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_bytes(config_module.CONFIG_PATH.read_bytes())
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
    monkeypatch.setenv("SENTINEL_JWT_SECRET", "isolated-config-regression-secret-123456789")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        admin = User(username="config-admin", role="admin", password_hash="unused-with-token-auth")
        db.add(admin)
        db.commit()
        headers = {"Authorization": f"Bearer {create_token(admin)}"}

    app = FastAPI()
    app.include_router(routes.router)

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, headers, path
    engine.dispose()


@pytest.mark.parametrize("path,invalid", INVALID_VALUES)
def test_config_put_rejects_invalid_values_without_rewriting_file(config_api, path, invalid):
    client, headers, config_path = config_api
    before = config_path.read_bytes()
    response = client.put("/api/config", headers=headers, json=_updates(path, invalid))
    assert response.status_code == 422
    assert config_path.read_bytes() == before
    assert not config_path.with_suffix(".yaml.tmp").exists()


def test_config_put_preserves_cors_origins_readonly_scope(config_api):
    client, headers, config_path = config_api
    before = config_path.read_bytes()
    response = client.put("/api/config", headers=headers, json={"app": {"cors_origins": [7]}})
    assert response.status_code == 422
    assert config_path.read_bytes() == before


@pytest.mark.parametrize("invalid", [[7], "http://localhost:5173", None])
def test_config_put_rejects_invalid_cors_in_full_policy_without_writes(config_api, invalid):
    client, headers, config_path = config_api
    before = config_path.read_bytes()
    body = client.get("/api/config", headers=headers).json()
    body["app"]["cors_origins"] = invalid
    body["fusion"]["strategy"] = "vote"
    assert client.put("/api/config", headers=headers, json=body).status_code == 422
    assert config_path.read_bytes() == before


def test_ollama_requirement_excludes_versions_before_0_6_3():
    declarations = (config_module.ROOT / "backend/requirements.txt").read_text().splitlines()
    requirement = next(Requirement(line) for line in declarations if line.startswith("ollama"))
    assert "0.6.2" not in requirement.specifier
    assert "0.6.3" in requirement.specifier
    assert "0.9.9" in requirement.specifier
    assert "1.0.0" not in requirement.specifier


def test_official_dataset_contract_is_integration_only():
    module = importlib.import_module("backend.tests.test_evaluation")
    marks = getattr(module.test_official_dataset_counts_schema_and_hashes, "pytestmark", [])
    assert any(mark.name == "integration" for mark in marks)
