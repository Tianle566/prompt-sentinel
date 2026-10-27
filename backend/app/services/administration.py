"""Shared account locks, safe audit entries, and custom research samples."""
from __future__ import annotations

import csv
import io
import threading

from sqlalchemy import select

from backend.app.db.models import AdminAudit, CustomSample

account_lock = threading.RLock()
rules_lock = threading.RLock()


def audit(db, user, action: str, target: str, details: dict | None = None) -> None:
    db.add(AdminAudit(user_id=user.id, action=action, target=str(target), details=details or {}))


def account_dict(user):
    return {"id": user.id, "username": user.username, "role": user.role, "is_active": user.is_active, "created_at": user.created_at}


def sample_dict(sample):
    return {key: getattr(sample, key) for key in ("id", "text", "lang", "attack_type", "label", "source", "oracle", "enabled", "created_at", "updated_at")} | {"origin": "custom"}


def active_samples(db):
    return [sample_dict(sample) for sample in db.scalars(select(CustomSample).where(CustomSample.enabled.is_(True)))]


def csv_text(columns, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(columns)
    for row in rows:
        # Prevent formula execution when exported user text is opened in Excel.
        writer.writerow(["'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value for value in row])
    return "\ufeff" + stream.getvalue()
