from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import ROOT, get_config
from backend.app.db.models import User
from backend.app.db.session import get_db

bearer = HTTPBearer(auto_error=False)
_secret: str | None = None


def _private_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)
    path.chmod(0o600)


def jwt_secret() -> str:
    global _secret
    if _secret is None:
        env = get_config()["auth"]["jwt_secret_env"]
        secret = os.environ.get(env)
        if not secret:
            path = ROOT / ".runtime" / "jwt-secret"
            if not path.exists():
                _private_write(path, secrets.token_urlsafe(48))
            secret = path.read_text().strip()
        _secret = secret
    return _secret


def bootstrap_users(db: Session) -> None:
    cfg = get_config()["auth"]
    credentials = {}
    for role in ("admin", "user"):
        username = cfg[f"{role}_username"]
        if db.scalar(select(User).where(User.username == username)):
            continue
        password = os.environ.get(cfg[f"{role}_password_env"]) or secrets.token_urlsafe(12)
        if len(password.encode()) > 72:
            raise ValueError("初始密码 UTF-8 长度不能超过 72 字节")
        db.add(User(username=username, role=role, password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()))
        credentials[role] = {"username": username, "password": password}
    db.commit()
    if credentials:
        path = ROOT / ".runtime" / "credentials.json"
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        _private_write(path, json.dumps(existing | credentials, indent=2, ensure_ascii=False))


def user_dict(user: User) -> dict:
    return {"id": user.id, "username": user.username, "role": user.role}


def _credential_version(user: User) -> str:
    # Bind sessions to the stored password without exposing its bcrypt hash.
    value = f"{user.password_hash}:{user.role}:{user.session_version}"
    return hmac.new(jwt_secret().encode(), value.encode(), hashlib.sha256).hexdigest()


def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user.id), "iat": now, "exp": now + timedelta(minutes=get_config()["auth"]["token_minutes"]), "ver": _credential_version(user)}, jwt_secret(), algorithm="HS256")


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(401, "请先登录", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(credentials.credentials, jwt_secret(), algorithms=["HS256"], options={"require": ["exp", "sub", "ver"]})
        user = db.get(User, int(payload["sub"]))
        if not user or not user.is_active or not isinstance(payload["ver"], str) or not hmac.compare_digest(payload["ver"], _credential_version(user)):
            raise ValueError("unknown user")
        return user
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(401, "登录已过期，请重新登录", headers={"WWW-Authenticate": "Bearer"})


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "此操作需要管理员权限")
    return user
