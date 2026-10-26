#!/usr/bin/env python3
"""Expose a verified completed CLI experiment in the web evaluation center."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def import_results(directory="results", username=None):
    from sqlalchemy import select
    from backend.app.core.config import get_config, public_config, resolve_path
    from backend.app.db.models import EvaluationJob, User
    from backend.app.db.session import SessionLocal
    source = resolve_path(directory).resolve()
    summary_file = source / "summary.json"
    summary = json.loads(summary_file.read_text())
    audit = json.loads((source / "independent_audit.json").read_text())
    if summary["status"] != "completed" or summary["errors"] or audit["status"] != "passed":
        raise ValueError("仅可导入已完整完成、无错误且通过独立审计的真实实验")
    source_hash = hashlib.sha256(summary_file.read_bytes()).hexdigest()
    username = username or get_config()["auth"]["admin_username"]
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username, User.role == "admin"))
        if not user:
            raise ValueError("请先启动后端生成管理员账户")
        for existing in db.scalars(select(EvaluationJob).where(EvaluationJob.user_id == user.id)):
            if (existing.result or {}).get("imported_from_summary_sha256") == source_hash:
                return existing.id
        job_id = uuid.uuid4().hex
        destination = ROOT / "results" / job_id
        destination.mkdir()
        names = set(summary.get("artifacts", [])) | {"summary.json", "config_snapshot.json", "independent_audit.json", "oracle_audit.jsonl", "oracle_audit_summary.json"}
        copied = []
        for name in sorted(names):
            if Path(name).name != name or Path(name).suffix not in (".csv", ".png", ".json", ".jsonl"):
                continue
            path = (source / name).resolve()
            if not path.is_relative_to(source) or not path.is_file():
                continue
            shutil.copy2(path, destination / name)
            copied.append(name)
        result = {**summary, "artifacts": copied, "origin": "verified completed CLI experiment", "imported_from_summary_sha256": source_hash}
        (destination / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        snapshot = json.loads((source / "config_snapshot.json").read_text())
        job = EvaluationJob(id=job_id, user_id=user.id, experiment=summary["experiment"], status="completed", progress=100, message="CLI 实验已完整完成并通过独立审计，结果已导入", config=public_config(snapshot), result=result, created_at=datetime.fromtimestamp((source / "config_snapshot.json").stat().st_mtime, timezone.utc))
        db.add(job)
        db.commit()
    report = {"job_id": job_id, "source_summary_sha256": source_hash, "artifacts": len(copied), "api": f"/api/eval/jobs/{job_id}", "source": str(source)}
    (ROOT / "results" / "import_verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return job_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default="results")
    parser.add_argument("--username")
    args = parser.parse_args()
    import_results(args.directory, args.username)
