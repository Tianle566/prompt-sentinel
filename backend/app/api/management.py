"""Administrator account, rule, policy history, sample, and audit management."""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import Literal

import bcrypt
import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.auth import _private_write, admin_user
from backend.app.core.config import ROOT, get_config, resolve_path
from backend.app.db.models import AdminAudit, CustomSample, PolicyAudit, User
from backend.app.db.session import get_db
from backend.app.services.administration import account_dict, account_lock, audit, csv_text, rules_lock, sample_dict

router = APIRouter(tags=["administration"])


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "admin"]
    is_active: bool


class ResetPassword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=72)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not 8 <= len(value.encode()) <= 72:
            raise ValueError("密码 UTF-8 长度必须为 8–72 字节")
        return value


@router.patch("/users/{user_id}")
def update_account(user_id: int, body: AccountUpdate, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    with account_lock:
        db.refresh(actor)
        if not actor.is_active or actor.role != "admin":
            raise HTTPException(403, "此操作需要有效的管理员权限")
        account = db.get(User, user_id)
        if account is None:
            raise HTTPException(404, "账号不存在")
        before = {"role": account.role, "is_active": account.is_active}
        if account.role == "admin" and account.is_active and (body.role != "admin" or not body.is_active):
            count = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True)))
            if count <= 1:
                raise HTTPException(409, "不能停用或降级最后一个有效管理员")
        if before != body.model_dump():
            account.role = body.role
            account.is_active = body.is_active
            account.session_version += 1
            audit(db, actor, "account.update", str(account.id), {"username": account.username, "before": before, "after": body.model_dump()})
            db.commit()
        return account_dict(account)


@router.post("/users/{user_id}/password")
def reset_account_password(user_id: int, body: ResetPassword, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    with account_lock:
        db.refresh(actor)
        if not actor.is_active or actor.role != "admin":
            raise HTTPException(403, "此操作需要有效的管理员权限")
        account = db.get(User, user_id)
        if account is None:
            raise HTTPException(404, "账号不存在")
        account.password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
        account.session_version += 1
        path = ROOT / ".runtime" / "credentials.json"
        if path.exists():
            credentials = json.loads(path.read_text(encoding="utf-8"))
            remaining = {key: value for key, value in credentials.items() if value.get("username") != account.username}
            if remaining != credentials:
                _private_write(path, json.dumps(remaining, ensure_ascii=False, indent=2))
        audit(db, actor, "account.password_reset", str(account.id), {"username": account.username})
        db.commit()
        return {"message": "密码已重置，该账号需重新登录"}


def rules_path():
    return resolve_path(get_config().get("rules_path", "backend/rules.yaml"))


class RuleEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    category: str = Field(min_length=1, max_length=80)
    pattern: str = Field(min_length=1, max_length=2000)
    enabled: bool = True

    @field_validator("pattern")
    @classmethod
    def compile_pattern(cls, value):
        try:
            re.compile(value, re.I | re.M)
        except re.error:
            raise ValueError("规则正则表达式无效")
        return value


class RuleDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    items: list[RuleEntry] = Field(max_length=2000)

    @model_validator(mode="after")
    def unique_ids(self):
        identifiers = [item.id for item in self.items]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("规则 ID 不能重复")
        return self


def read_rules():
    document = yaml.safe_load(rules_path().read_text(encoding="utf-8"))
    return {"version": int(document.get("version", 1)), "items": [RuleEntry.model_validate(entry).model_dump() for entry in document["rules"]]}


def write_rules(body: dict):
    path = rules_path()
    temporary = path.with_suffix(".yaml.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump({"version": body["version"], "rules": body["items"]}, handle, allow_unicode=True, sort_keys=False)
    os.replace(temporary, path)


@router.get("/admin/rules")
def get_rules(actor: User = Depends(admin_user)):
    with rules_lock:
        return read_rules()


@router.put("/admin/rules")
def save_rules(body: RuleDocument, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    with rules_lock:
        before = read_rules()
        if body.version != before["version"]:
            raise HTTPException(409, "规则已被其他操作更新，请刷新后重试")
        after = body.model_dump() | {"version": before["version"] + 1}
        write_rules(after)
        audit(db, actor, "rules.update", str(after["version"]), {"before": before, "after": after})
        db.commit()
        return after


@router.get("/admin/rules/history")
def rules_history(actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AdminAudit).where(AdminAudit.action.in_(["rules.update", "rules.restore"])).order_by(AdminAudit.id.desc()).limit(100))
    return {"items": [{"id": row.id, "user_id": row.user_id, "created_at": row.created_at, "before": row.details["before"], "after": row.details["after"]} for row in rows]}


class RestoreBody(BaseModel):
    side: Literal["before", "after"] = "before"


@router.post("/admin/rules/history/{audit_id}/restore")
def restore_rules(audit_id: int, body: RestoreBody, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    record = db.get(AdminAudit, audit_id)
    if not record or record.action not in ("rules.update", "rules.restore"):
        raise HTTPException(404, "规则历史不存在")
    with rules_lock:
        before = read_rules()
        restored = RuleDocument.model_validate(record.details[body.side])
        after = restored.model_dump() | {"version": before["version"] + 1}
        write_rules(after)
        audit(db, actor, "rules.restore", str(after["version"]), {"history_id": audit_id, "before": before, "after": after})
        db.commit()
        return after


@router.get("/admin/policy/history")
def policy_history(actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.execute(select(PolicyAudit, User.username).join(User, User.id == PolicyAudit.user_id).order_by(PolicyAudit.id.desc()).limit(100))
    return {"items": [{"id": row.id, "username": username, "created_at": row.created_at, "before": row.before, "after": row.after} for row, username in rows]}


@router.post("/admin/policy/history/{audit_id}/restore")
def restore_policy(audit_id: int, body: RestoreBody, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    from backend.app.api.routes import _policy_updates
    from backend.app.core.config import public_config, save_config
    record = db.get(PolicyAudit, audit_id)
    if record is None:
        raise HTTPException(404, "策略历史不存在")
    before = public_config()
    snapshot = getattr(record, body.side)
    updates = _policy_updates(snapshot)
    prior_limits = snapshot.get("evaluation", {})
    updates["evaluation"] = {key: prior_limits.get(key, default) for key, default in {"max_detection_samples": 5000, "max_asr_samples": 200, "max_queued_jobs": 2, "time_budget_seconds": 7000}.items()}
    after = public_config(save_config(updates))
    db.add(PolicyAudit(user_id=actor.id, before=before, after=after))
    audit(db, actor, "policy.restore", str(audit_id), {"side": body.side})
    db.commit()
    return after


class SampleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=30000)
    lang: Literal["zh", "en"] = "zh"
    attack_type: Literal["goal_hijacking", "prompt_leaking", "role_play", "encoded", "indirect", "benign"]
    label: Literal[0, 1] = 1
    source: str = Field(min_length=1, max_length=200)
    oracle: dict = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def explicit_oracle(self):
        if not self.text.strip() or not self.source.strip():
            raise ValueError("样本内容和来源不能为空白")
        if (self.label == 0) != (self.attack_type == "benign"):
            raise ValueError("正常样本的类别必须为 benign，攻击样本标签必须为 1")
        kind = self.oracle.get("type")
        if self.label == 1 and kind not in ("marker", "canary", "guard_unsafe"):
            raise ValueError("攻击样本必须指定成功判据")
        if kind == "marker":
            marker = self.oracle.get("marker")
            if not isinstance(marker, str) or not marker.strip() or len(marker) > 100:
                raise ValueError("标记判据需要 1–100 字符的有效标记")
            self.oracle = {"type": "marker", "marker": marker}
        else:
            self.oracle = {"type": kind} if self.label else {}
        return self


@router.get("/admin/samples")
def samples(origin: Literal["all", "custom", "builtin"] = "all", q: str = Query("", max_length=100), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    from backend.app.services.evaluation import load_samples
    items = [sample_dict(row) for row in db.scalars(select(CustomSample).order_by(CustomSample.created_at.desc()))] if origin != "builtin" else []
    if origin != "custom":
        try:
            items += [row | {"origin": "builtin", "enabled": True} for row in load_samples("asr")]
        except FileNotFoundError:
            pass
    if q:
        items = [row for row in items if q.lower() in (row["text"] + " " + row["source"] + " " + str(row["id"])).lower()]
    start = (page - 1) * page_size
    return {"items": items[start:start + page_size], "total": len(items), "page": page, "page_size": page_size}


@router.post("/admin/samples", status_code=201)
def create_sample(body: SampleBody, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    row = CustomSample(id="custom_" + uuid.uuid4().hex, user_id=actor.id, **body.model_dump())
    db.add(row)
    audit(db, actor, "sample.create", row.id, {"source": row.source, "attack_type": row.attack_type})
    db.commit()
    return sample_dict(row)


@router.put("/admin/samples/{sample_id}")
def update_sample(sample_id: str, body: SampleBody, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    row = db.get(CustomSample, sample_id)
    if row is None:
        raise HTTPException(404, "只能编辑自定义样本，论文样本为只读")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    audit(db, actor, "sample.update", sample_id, {"source": row.source, "enabled": row.enabled})
    db.commit()
    return sample_dict(row)


@router.delete("/admin/samples/{sample_id}")
def delete_sample(sample_id: str, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    row = db.get(CustomSample, sample_id)
    if row is None:
        raise HTTPException(404, "只能移除自定义样本，论文样本为只读")
    audit(db, actor, "sample.delete", sample_id, {"source": row.source, "attack_type": row.attack_type})
    db.delete(row)
    db.commit()
    return {"message": "自定义样本已移除，历史测试记录保留"}


@router.get("/admin/audits")
def audit_list(action: str | None = Query(None, max_length=80), user_id: int | None = Query(None, ge=1), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    statement = select(AdminAudit, User.username).join(User, User.id == AdminAudit.user_id)
    if action:
        statement = statement.where(AdminAudit.action == action)
    if user_id:
        statement = statement.where(AdminAudit.user_id == user_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = db.execute(statement.order_by(AdminAudit.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return {"items": [{"id": row.id, "username": username, "action": row.action, "target": row.target, "details": row.details, "created_at": row.created_at} for row, username in rows], "total": total}


@router.get("/admin/audits/export.csv")
def export_audits(action: str | None = Query(None, max_length=80), user_id: int | None = Query(None, ge=1), actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    data = audit_list(action, user_id, 1, 10000, actor, db)
    text = csv_text(["ID", "操作人", "操作", "对象", "时间", "详情"], [[row["id"], row["username"], row["action"], row["target"], str(row["created_at"]), json.dumps(row["details"], ensure_ascii=False)] for row in data["items"]])
    return Response(text, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="admin-audits.csv"'})
