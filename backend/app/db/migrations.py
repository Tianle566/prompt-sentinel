"""Additive schema upgrades with a consistent SQLite backup before alteration."""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect, text

from backend.app.core.config import ROOT
from backend.app.db.models import Base


def backup_sqlite(engine, directory: Path, prefix: str = "sentinel") -> Path:
    if engine.dialect.name != "sqlite":
        raise ValueError("此功能仅支持本地 SQLite 数据库")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{prefix}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}.db"
    with engine.connect() as connection:
        source = connection.connection.driver_connection
        database = source.execute("PRAGMA database_list").fetchone()[2]
        if not database:
            raise ValueError("内存数据库不支持文件备份")
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            target = sqlite3.connect(path)
            try:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("数据库备份完整性检查失败")
            finally:
                target.close()
        except Exception:
            path.unlink(missing_ok=True)
            raise
    return path


def initialize_database(engine) -> None:
    additions = {
        "users": {"is_active": "BOOLEAN NOT NULL DEFAULT 1", "session_version": "INTEGER NOT NULL DEFAULT 0"},
        "evaluation_jobs": {"cancel_requested": "BOOLEAN NOT NULL DEFAULT 0", "archived": "BOOLEAN NOT NULL DEFAULT 0"},
    }
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    changes = []
    for table, columns in additions.items():
        present = {column["name"] for column in inspector.get_columns(table)} if table in existing else set(columns)
        changes.extend(f"ALTER TABLE {table} ADD COLUMN {name} {definition}" for name, definition in columns.items() if name not in present)
    if changes and engine.dialect.name == "sqlite":
        with engine.connect() as connection:
            persistent = bool(connection.exec_driver_sql("PRAGMA database_list").fetchone()[2])
        if persistent:
            backup_sqlite(engine, ROOT / ".runtime" / "backups", "before-admin-upgrade")
    with engine.begin() as connection:
        for statement in changes:
            connection.execute(text(statement))
    Base.metadata.create_all(engine)
