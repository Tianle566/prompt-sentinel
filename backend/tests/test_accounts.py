"""Account persistence, authorization, and password-session regressions."""
import json

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.app.api import routes
from backend.app.core import auth
from backend.app.db.models import Base, User
from backend.app.db.session import get_db
from backend.tests.test_api import api


@pytest.fixture
def accounts_api(api, monkeypatch, tmp_path):
    routes._login_attempts.clear()
    monkeypatch.setattr(routes, "ROOT", tmp_path)
    monkeypatch.setattr(auth, "ROOT", tmp_path)
    yield api
    routes._login_attempts.clear()


@pytest.mark.parametrize("role", ["user", "admin"])
def test_admin_creates_hashed_accounts_without_plaintext_files(accounts_api, tmp_path, role):
    client, admin, _, sessions = accounts_api
    response = client.post("/api/users", headers=admin, json={"username": "  研究员_01  ", "password": "密码安全", "role": role})
    assert response.status_code == 201
    account = response.json()
    assert set(account) == {"id", "username", "role", "is_active", "created_at"}
    assert account["username"] == "研究员_01" and account["role"] == role
    assert account["created_at"]
    with sessions() as db:
        saved = db.get(User, account["id"])
        assert saved.password_hash != "密码安全"
        assert bcrypt.checkpw("密码安全".encode(), saved.password_hash.encode())
    assert not (tmp_path / ".runtime" / "credentials.json").exists()
    login = client.post("/api/auth/login", json={"username": "研究员_01", "password": "密码安全"})
    assert login.status_code == 200 and login.json()["user"]["role"] == role


def test_account_management_requires_admin(accounts_api):
    client, _, user, sessions = accounts_api
    body = {"username": "new-user", "password": "new-user-password", "role": "admin"}
    for headers, status in [({}, 401), (user, 403)]:
        assert client.get("/api/users", headers=headers).status_code == status
        assert client.post("/api/users", headers=headers, json=body).status_code == status
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 2


def test_account_list_is_paginated_and_never_returns_passwords(accounts_api):
    client, admin, _, _ = accounts_api
    response = client.get("/api/users?page_size=1&page=2", headers=admin)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2 and data["page"] == 2 and data["page_size"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["username"] == "test-user"
    assert set(data["items"][0]) == {"id", "username", "role", "is_active", "created_at"}
    assert client.get("/api/users?page=0", headers=admin).status_code == 422
    assert client.get("/api/users?page_size=101", headers=admin).status_code == 422


@pytest.mark.parametrize("changes", [
    {"username": " "},
    {"username": "has space"},
    {"username": "bad/name"},
    {"username": "a" * 81},
    {"password": "short"},
    {"password": "a" * 73},
    {"password": "密" * 25},
    {"role": "superadmin"},
    {"password_hash": "supplied-hash"},
])
def test_invalid_accounts_are_not_saved(accounts_api, changes):
    client, admin, _, sessions = accounts_api
    body = {"username": "new-user", "password": "valid-password", "role": "user"} | changes
    assert client.post("/api/users", headers=admin, json=body).status_code == 422
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 2


def test_duplicate_username_preserves_existing_password(accounts_api):
    client, admin, _, sessions = accounts_api
    with sessions() as db:
        original = db.get(User, 2).password_hash
    response = client.post("/api/users", headers=admin, json={"username": " test-user ", "password": "replacement-password"})
    assert response.status_code == 409
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 2
        assert db.get(User, 2).password_hash == original


def test_unique_constraint_race_rolls_back_cleanly(accounts_api, monkeypatch):
    client, admin, _, sessions = accounts_api
    original_flush = sessions.class_.flush
    def conflicting_flush(db, *args, **kwargs):
        if any(isinstance(item, User) and item.username == "conflicting-user" for item in db.new):
            raise IntegrityError("duplicate username", {}, Exception("unique constraint"))
        original_flush(db, *args, **kwargs)
    monkeypatch.setattr(sessions.class_, "flush", conflicting_flush)
    response = client.post("/api/users", headers=admin, json={"username": "conflicting-user", "password": "valid-password"})
    assert response.status_code == 409
    assert client.get("/api/users", headers=admin).json()["total"] == 2


def test_password_change_revokes_all_old_sessions_and_preserves_other_accounts(accounts_api, tmp_path):
    client, admin, user, sessions = accounts_api
    second = client.post("/api/auth/login", json={"username": "test-user", "password": "user-test-password"}).json()
    second_headers = {"Authorization": f"Bearer {second['access_token']}"}
    credentials_path = tmp_path / ".runtime" / "credentials.json"
    credentials_path.parent.mkdir()
    credentials_path.write_text(json.dumps({"user": {"username": "test-user", "password": "user-test-password"}, "admin": {"username": "test-admin", "password": "admin-test-password"}}), encoding="utf-8")
    assert client.post("/api/auth/password", headers=user, json={"old_password": "user-test-password", "new_password": "new-account-password"}).status_code == 200
    for headers in (user, second_headers):
        assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.get("/api/auth/me", headers=admin).status_code == 200
    assert client.post("/api/auth/login", json={"username": "test-user", "password": "user-test-password"}).status_code == 401
    fresh = client.post("/api/auth/login", json={"username": "test-user", "password": "new-account-password"})
    assert fresh.status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {fresh.json()['access_token']}"}).status_code == 200
    assert set(json.loads(credentials_path.read_text(encoding="utf-8"))) == {"admin"}
    with sessions() as db:
        assert bcrypt.checkpw(b"admin-test-password", db.get(User, 1).password_hash.encode())


def test_created_account_survives_database_and_app_restart(accounts_api, tmp_path):
    _, _, _, fixture_sessions = accounts_api
    database_url = f"sqlite:///{(tmp_path / 'accounts.db').as_posix()}"
    def application():
        engine = create_engine(database_url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        app = FastAPI()
        app.include_router(routes.router)
        def database():
            with sessions() as db:
                yield db
        app.dependency_overrides[get_db] = database
        return app, engine, sessions
    app, engine, sessions = application()
    with fixture_sessions() as db, sessions() as stored:
        original = db.get(User, 1)
        stored.add(User(username=original.username, role=original.role, password_hash=original.password_hash))
        stored.commit()
    with TestClient(app) as client:
        admin = client.post("/api/auth/login", json={"username": "test-admin", "password": "admin-test-password"}).json()
        response = client.post("/api/users", headers={"Authorization": f"Bearer {admin['access_token']}"}, json={"username": "persisted-user", "password": "persisted-password"})
        assert response.status_code == 201
    engine.dispose()
    restarted_app, restarted_engine, _ = application()
    with TestClient(restarted_app) as client:
        response = client.post("/api/auth/login", json={"username": "persisted-user", "password": "persisted-password"})
        assert response.status_code == 200
        assert response.json()["user"]["username"] == "persisted-user"
        assert response.json()["user"]["role"] == "user"
    restarted_engine.dispose()
