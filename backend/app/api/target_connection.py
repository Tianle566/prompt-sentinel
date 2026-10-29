"""Administrator-only OpenAI-compatible connection import and verification."""
from __future__ import annotations

import os
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from sqlalchemy.orm import Session

from backend.app.core import config as configuration
from backend.app.core.auth import admin_user
from backend.app.core.config import get_config, merge_dict, public_config, save_config, validate_config
from backend.app.core.target_credentials import (
    CredentialError, connection_lock, credential_for, credential_status, normalize_api_key,
    normalize_base_url, read_saved_credential, write_saved_credential,
)
from backend.app.db.models import PolicyAudit, User
from backend.app.db.session import get_db
from backend.app.llm.target import TargetError, TargetLLM
from backend.app.services.administration import audit


class PrivateValidationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                errors = [{key: item[key] for key in ("type", "loc", "msg")} for item in exc.errors()]
                raise HTTPException(422, errors) from None

        return safe_handler


router = APIRouter(tags=["target-connection"], route_class=PrivateValidationRoute)


class ConnectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["ollama", "openai"]
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(default="", max_length=200)
    api_key: SecretStr | None = None
    clear_api_key: bool = False
    small_model: str | None = Field(default=None, min_length=1, max_length=200)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    max_tokens: int | None = Field(default=None, ge=1, le=8192)
    temperature: float | None = Field(default=None, ge=0, le=2)
    context_length: int | None = Field(default=None, ge=512, le=131072)
    system_prompt: str | None = Field(default=None, max_length=8000)

    @field_validator("api_key")
    @classmethod
    def key_format(cls, value):
        return SecretStr(normalize_api_key(value.get_secret_value())) if value is not None else None

    @model_validator(mode="after")
    def endpoint_format(self):
        self.base_url = normalize_base_url(self.base_url, self.provider)
        self.model = self.model.strip()
        key = self.api_key.get_secret_value() if self.api_key is not None else ""
        if key and self.clear_api_key:
            raise ValueError("不能同时填写新密钥并清除密钥")
        if key and self.provider != "openai":
            raise ValueError("API Key 仅用于 OpenAI 兼容接口")
        return self


def draft(body: ConnectionBody, require_model: bool = True) -> dict:
    updates = body.model_dump(exclude={"api_key", "clear_api_key"}, exclude_none=True, exclude_unset=True)
    updates.update(provider=body.provider, base_url=body.base_url)
    if require_model and not body.model:
        raise HTTPException(422, "请填写模型名称或先获取模型列表")
    if not body.model:
        updates.pop("model", None)
    else:
        updates["model"] = body.model
    try:
        return validate_config(merge_dict(get_config(), {"target": updates}))
    except (ValueError, TypeError, KeyError):
        raise HTTPException(422, "连接参数无效，请检查地址、模型和生成设置") from None


def selected_key(body: ConnectionBody, settings: dict) -> str:
    if body.api_key is not None and body.api_key.get_secret_value():
        return body.api_key.get_secret_value()
    try:
        return credential_for(settings, use_saved=not body.clear_api_key)[0] if settings["provider"] == "openai" else ""
    except CredentialError as exc:
        raise HTTPException(409, str(exc)) from None


def response_state():
    target = public_config()["target"]
    try:
        status = credential_status(target)
    except CredentialError as exc:
        status = {"configured": False, "source": "error", "saved": False, "error": str(exc)}
    return {"target": target, "credential": status}


@router.get("/admin/target")
def read_connection(actor: User = Depends(admin_user)):
    return response_state()


@router.put("/admin/target")
def save_connection(body: ConnectionBody, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    with connection_lock, configuration._lock:
        after = draft(body)
        before = get_config()
        original_config = configuration.CONFIG_PATH.read_bytes()
        try:
            old_key = read_saved_credential()
        except CredentialError:
            old_key = None
        fresh_key = body.api_key.get_secret_value() if body.api_key is not None else ""
        change_key = bool(fresh_key) or body.clear_api_key
        new_key = {"version": 1, "base_url": body.base_url, "api_key": fresh_key} if fresh_key else None
        config_saved = False
        try:
            if change_key:
                write_saved_credential(new_key)
            save_config({"target": after["target"]})
            config_saved = True
            db.add(PolicyAudit(user_id=actor.id, before=public_config(before), after=public_config(after)))
            audit(db, actor, "target.connection", "target", {
                "provider": body.provider, "base_url": body.base_url, "model": body.model,
                "key_updated": bool(fresh_key), "key_cleared": body.clear_api_key,
            })
            db.commit()
        except Exception:
            db.rollback()
            if config_saved:
                temporary = configuration.CONFIG_PATH.with_suffix(".yaml.rollback.tmp")
                temporary.write_bytes(original_config)
                os.replace(temporary, configuration.CONFIG_PATH)
            if change_key:
                write_saved_credential(old_key)
            raise HTTPException(500, "连接保存失败，原配置已恢复") from None
        return response_state()


@router.post("/admin/target/models")
def list_connection_models(body: ConnectionBody, actor: User = Depends(admin_user)):
    config = draft(body, require_model=False)
    config["target"]["timeout_seconds"] = min(10, config["target"]["timeout_seconds"])
    key = selected_key(body, config["target"])
    try:
        models = TargetLLM(config, api_key_override=key).list_models()
        return {"models": [name for name in models if not key or key not in name][:500]}
    except TargetError as exc:
        raise HTTPException(502, str(exc)) from None


@router.post("/admin/target/test")
def test_connection(body: ConnectionBody, actor: User = Depends(admin_user)):
    config = draft(body)
    config["target"].update(timeout_seconds=min(30, config["target"]["timeout_seconds"]), max_tokens=min(64, config["target"]["max_tokens"]))
    key = selected_key(body, config["target"])
    started = time.perf_counter()
    try:
        target = TargetLLM(config, api_key_override=key)
        target.generate([{"role": "user", "content": "Reply with OK."}])
    except TargetError as exc:
        raise HTTPException(502, str(exc)) from None
    return {"ok": True, "model": target.model, "latency_ms": round((time.perf_counter() - started) * 1000, 1)}
