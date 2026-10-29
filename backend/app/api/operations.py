"""Evaluation lifecycle and local runtime maintenance, with preserved evidence."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import httpx
import psutil
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.auth import admin_user, current_user
from backend.app.core.config import ROOT, get_config, public_config, save_config
from backend.app.core.target_credentials import saved_secret_values
from backend.app.db.migrations import backup_sqlite
from backend.app.db.models import EvaluationJob, User
from backend.app.db.session import get_db
from backend.app.services.administration import audit
from backend.app.services.evaluation import ensure_local_target

router = APIRouter(tags=["operations"])
RUNNING = ("queued", "running", "cancelling")


@router.post("/eval/jobs/{job_id}/cancel")
def cancel_job(job_id: str, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    from backend.app.api.routes import _get_job, _job_dict
    job = _get_job(job_id, actor, db)
    if job.status not in RUNNING:
        raise HTTPException(409, "只能取消排队或运行中的任务")
    job.cancel_requested = True
    job.status = "cancelled" if job.status == "queued" else "cancelling"
    job.message = "已取消排队任务" if job.status == "cancelled" else "正在取消，当前样本处理结束后停止并保留结果"
    audit(db, actor, "evaluation.cancel", job.id)
    db.commit()
    return _job_dict(job)


class ArchiveBody(BaseModel):
    archived: bool


@router.post("/eval/jobs/{job_id}/archive")
def archive_job(job_id: str, body: ArchiveBody, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    from backend.app.api.routes import _get_job, _job_dict
    job = _get_job(job_id, actor, db)
    if job.status in RUNNING:
        raise HTTPException(409, "运行中的任务需先结束或取消")
    job.archived = body.archived
    audit(db, actor, "evaluation.archive" if body.archived else "evaluation.unarchive", job.id)
    db.commit()
    return _job_dict(job)


@router.get("/eval/compare")
def compare_jobs(job_ids: str, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    from backend.app.api.routes import _get_job
    identifiers = list(dict.fromkeys(job_ids.split(",")))
    if not 2 <= len(identifiers) <= 4:
        raise HTTPException(422, "请选择 2–4 个不同任务进行对比")
    items, protocols = [], []
    for identifier in identifiers:
        job = _get_job(identifier, actor, db)
        result = job.result
        if not result or job.status in RUNNING:
            raise HTTPException(409, "仅可对比已有结果且已结束的任务")
        tables = result.get("tables", {})
        detection = next((row for row in tables.get("detection", []) if row.get("configuration") == "any" and row.get("lang") == "all"), {})
        defense = next((row for row in tables.get("defense", []) if row.get("configuration") == "full" and row.get("attack_type") == "all"), {})
        overhead = next((row for row in tables.get("overhead", []) if row.get("layer") == "pipeline_total"), {})
        items.append({"id": job.id, "experiment": job.experiment, "status": job.status, "created_at": job.created_at, "f1": detection.get("f1"), "asr": defense.get("asr"), "latency_ms": overhead.get("mean_ms"), "detection_evaluated": detection.get("evaluated"), "asr_evaluated": defense.get("evaluated"), "data_scope": result.get("data_scope"), "configuration": job.config})
        identity = {key: result.get(key) for key in ("experiment", "seed", "data_scope", "dataset_hashes", "environment")}
        identity["inference_fingerprint"] = result.get("inference", {}).get("fingerprint")
        protocols.append(json.dumps(identity, sort_keys=True) + json.dumps(job.config, sort_keys=True))
    return {"items": items, "same_protocol": len(set(protocols)) == 1, "note": "只并列展示各任务的真实结果；样本、模型或策略不一致时不能直接归因于某项改进。取消或未完成任务的指标仅代表已完成范围。"}


class RuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_detection_samples: int = Field(ge=1, le=100000)
    max_asr_samples: int = Field(ge=1, le=1000)
    max_queued_jobs: int = Field(ge=1, le=4)
    time_budget_seconds: int = Field(ge=30, le=7200)
    model: str = Field(min_length=1, max_length=200)
    max_tokens: int = Field(ge=1, le=8192)
    context_length: int = Field(ge=512, le=131072)
    temperature: float = Field(ge=0, le=2)
    timeout_seconds: int = Field(ge=1, le=600)


def runtime_settings(config):
    limits = config["evaluation"]
    return {"max_detection_samples": limits.get("max_detection_samples", 5000), "max_asr_samples": limits.get("max_asr_samples", 200), "max_queued_jobs": limits.get("max_queued_jobs", 2), "time_budget_seconds": int(limits["time_budget_seconds"])} | {key: config["target"][key] for key in ("model", "max_tokens", "context_length", "temperature", "timeout_seconds")}


@router.get("/admin/runtime")
def runtime(actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    config = get_config()
    available, model_error = [], None
    if config["target"]["provider"] == "ollama":
        try:
            ensure_local_target(config)
            response = httpx.get(config["target"]["base_url"].rstrip("/") + "/api/tags", timeout=3)
            response.raise_for_status()
            available = [{"name": row["name"], "size": row.get("size")} for row in response.json().get("models", [])]
        except (ValueError, httpx.HTTPError, KeyError):
            model_error = "目标模型服务未就绪，启动项目后可查看已安装模型。"
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(ROOT))
    return {"settings": runtime_settings(config), "models": available, "model_error": model_error, "device": config["models"]["device"], "memory": {"total": memory.total, "available": memory.available}, "disk": {"total": disk.total, "free": disk.free}, "active_jobs": db.scalar(select(func.count()).select_from(EvaluationJob).where(EvaluationJob.status.in_(RUNNING))), "sqlite_backup_supported": db.bind.dialect.name == "sqlite"}


@router.put("/admin/runtime/settings")
def set_runtime(body: RuntimeSettings, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    before = get_config()
    target = {key: getattr(body, key) for key in ("model", "max_tokens", "context_length", "temperature", "timeout_seconds")}
    if not body.model.strip():
        raise HTTPException(422, "模型名称不能为空白")
    evaluation = {key: getattr(body, key) for key in ("max_detection_samples", "max_asr_samples", "max_queued_jobs", "time_budget_seconds")}
    after = save_config({"evaluation": evaluation, "target": target})
    from backend.app.db.models import PolicyAudit
    db.add(PolicyAudit(user_id=actor.id, before=public_config(before), after=public_config(after)))
    audit(db, actor, "runtime.settings", "runtime", {"before": runtime_settings(before), "after": runtime_settings(after)})
    db.commit()
    return runtime_settings(after)


def backup_directory():
    return ROOT / ".runtime" / "backups"


@router.get("/admin/backups")
def list_backups(actor: User = Depends(admin_user)):
    directory = backup_directory()
    return {"items": [{"filename": path.name, "bytes": path.stat().st_size, "modified_at": path.stat().st_mtime} for path in sorted(directory.glob("*.db"), key=lambda value: value.stat().st_mtime, reverse=True) if path.is_file() and not path.is_symlink()]}


@router.post("/admin/backups", status_code=201)
def create_backup(actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    try:
        path = backup_sqlite(db.bind, backup_directory())
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    audit(db, actor, "database.backup", path.name)
    db.commit()
    return {"filename": path.name, "bytes": path.stat().st_size}


@router.get("/admin/backups/{filename}")
def download_backup(filename: str, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    if not re.fullmatch(r"[A-Za-z0-9-]+\.db", filename):
        raise HTTPException(404, "备份不存在")
    path = backup_directory() / filename
    if not path.is_file() or path.is_symlink():
        raise HTTPException(404, "备份不存在")
    audit(db, actor, "database.backup_download", filename)
    db.commit()
    return FileResponse(path, filename=filename, media_type="application/octet-stream")


@router.get("/admin/runtime/errors/{name}")
def runtime_errors(name: str, actor: User = Depends(admin_user)):
    if name not in ("backend", "frontend", "ollama"):
        raise HTTPException(404, "日志不存在")
    path = ROOT / ".runtime" / (name + ".log")
    if not path.is_file() or path.is_symlink():
        return {"text": "暂无运行日志", "truncated": False}
    with path.open("rb") as handle:
        size = path.stat().st_size
        handle.seek(max(0, size - 65536))
        text = handle.read().decode("utf-8", errors="replace")
    config = get_config()
    sensitive = [os.environ.get(value) for key, value in config["auth"].items() if key.endswith("_env")]
    sensitive.append(os.environ.get(config["target"].get("api_key_env", "TARGET_API_KEY")))
    sensitive.extend(saved_secret_values())
    credentials_path = ROOT / ".runtime" / "credentials.json"
    try:
        credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
        sensitive.extend(value.get("password") for value in credentials.values())
    except (OSError, ValueError):
        pass
    try:
        sensitive.append((ROOT / ".runtime" / "jwt-secret").read_text(encoding="utf-8").strip())
    except OSError:
        pass
    for value in sensitive:
        if value:
            text = text.replace(value, "[已隐藏]")
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._-]+", r"\1[已隐藏]", text)
    text = re.sub(r'''(?i)(["']?(?:password|api_key|secret|access_token)["']?\s*[:=]\s*)(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,}]+)''', r"\1[已隐藏]", text)
    return {"text": text, "truncated": size > 65536}
