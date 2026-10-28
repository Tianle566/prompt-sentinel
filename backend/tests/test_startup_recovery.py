"""Readiness checks and installation retries are offline and preserve user files."""
from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import bootstrap, doctor


@pytest.mark.parametrize("version,expected", [
    ("v20.18.3", False), ("v20.19.0", True), ("v21.7.3", False),
    ("v22.11.0", False), ("v22.12.0", True), ("v24.0.0", True),
    ("v18.20.8", False), ("broken", False),
])
def test_node_engine_requirement(version, expected):
    assert doctor.supported_node(version) is expected


def test_all_declared_dependencies_are_checked_with_versions(tmp_path, monkeypatch):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("# comment\nfastapi>=0.115,<1\nPyYAML>=6,<7\npsutil>=6,<8\n", encoding="utf-8")

    def installed(name):
        if name == "psutil":
            raise importlib.metadata.PackageNotFoundError(name)
        return {"fastapi": "0.120.0", "PyYAML": "5.4"}[name]

    monkeypatch.setattr(importlib.metadata, "version", installed)
    missing = bootstrap.missing_requirements(requirements)
    assert len(missing) == 2 and "PyYAML" in missing[0] and "psutil" in missing[1]


def test_interrupted_install_is_retried_without_removing_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    marker = tmp_path / "existing-database.db"
    marker.write_bytes(b"preserve")
    attempts = iter([["SQLAlchemy>=2,<3"], []])
    monkeypatch.setattr(bootstrap, "missing_requirements", lambda _: next(attempts))
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: None)
    calls = []
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=0))
    assert bootstrap.main() == 0
    assert len(calls) == 1 and calls[0][1:4] == ["-m", "pip", "install"]
    assert marker.read_bytes() == b"preserve"


def test_failed_install_keeps_retryable_state(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    monkeypatch.setattr(bootstrap, "missing_requirements", lambda _: ["httpx"])
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: "uv")
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=7))
    assert bootstrap.main() == 7


def test_doctor_reports_missing_files_without_writes_or_network(tmp_path, monkeypatch):
    from backend.app.core import config
    original = config.get_config()
    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    monkeypatch.setattr(doctor, "missing_requirements", lambda _: [])
    monkeypatch.setattr(doctor, "node_version", lambda: "v24.0.0")
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)
    monkeypatch.setattr(config, "get_config", lambda: original)
    monkeypatch.setattr(config, "resolve_path", lambda path: tmp_path / path)
    result = doctor.diagnose()
    assert result["ok"] is False
    assert {row["name"] for row in result["checks"] if not row["ok"]} >= {"npm", "前端依赖", "deberta", "qwen_guard", "目标模型", "Ollama", "detect_path", "asr_path"}
    assert list(tmp_path.iterdir()) == []
    assert "password" not in json.dumps(result) and "jwt" not in json.dumps(result)


def test_node_process_timeout_is_reported_as_missing(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _: "node")
    monkeypatch.setattr(doctor.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("node", 10)))
    assert doctor.node_version() is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows batch launcher")
def test_windows_check_does_not_create_an_environment(tmp_path):
    root = tmp_path / "new project 测试"
    root.mkdir()
    (root / "start.bat").write_bytes((bootstrap.ROOT / "start.bat").read_bytes())
    result = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "start.bat", "--check"], cwd=root, capture_output=True, timeout=15)
    assert result.returncode == 1
    assert {path.name for path in root.iterdir()} == {"start.bat"}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows batch launcher")
def test_windows_launcher_retries_a_partially_installed_environment(tmp_path):
    root = tmp_path / "retry project 测试"
    (root / "scripts").mkdir(parents=True)
    (root / "start.bat").write_bytes((bootstrap.ROOT / "start.bat").read_bytes())
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(root / ".venv")], check=True, timeout=30)
    interpreter = root / ".venv/Scripts/python.exe"
    original = interpreter.stat().st_mtime_ns
    (root / "scripts/bootstrap.py").write_text(
        "from pathlib import Path\nimport sys\nmarker=Path('retried')\n"
        "if not marker.exists():\n    marker.write_text('preserve')\n    sys.exit(3)\n", encoding="utf-8")
    (root / "scripts/serve.py").write_text("from pathlib import Path\nPath('started').write_text('ok')\n", encoding="utf-8")
    # A stale stop marker must not hide an actual setup failure.
    (root / ".runtime").mkdir()
    (root / ".runtime/stop.request").write_text("old stop", encoding="utf-8")
    command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "start.bat"]
    first = subprocess.run(command, cwd=root, input=b"\n", capture_output=True, timeout=20)
    assert first.returncode == 1 and not (root / "started").exists()
    second = subprocess.run(command, cwd=root, input=b"\n", capture_output=True, timeout=20)
    assert second.returncode == 0 and (root / "started").read_text() == "ok"
    assert interpreter.stat().st_mtime_ns == original
