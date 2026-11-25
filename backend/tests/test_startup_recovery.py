"""Readiness checks and installation retries are offline and preserve user files."""
from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import bootstrap, doctor, serve


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
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)
    monkeypatch.setattr(config, "get_config", lambda: original)
    monkeypatch.setattr(config, "resolve_path", lambda path: tmp_path / path)
    result = doctor.diagnose()
    assert result["ok"] is False
    assert {row["name"] for row in result["checks"] if not row["ok"]} >= {"npm", "前端依赖", "deberta", "qwen_guard", "目标模型", "Ollama", "detect_path", "asr_path"}
    assert list(tmp_path.iterdir()) == []
    assert "password" not in json.dumps(result) and "jwt" not in json.dumps(result)


@pytest.mark.parametrize("review_ready", [None, False, True])
def test_doctor_warns_about_optional_evaluation_files(tmp_path, monkeypatch, capsys, review_ready):
    from backend.app.core import config
    from backend.app.detectors import document_guard

    settings = config.get_config()
    settings["target"]["provider"] = "openai"
    settings["documents"] = {"review_enabled": review_ready is not None}
    settings["models"]["document_guard"] = {"path": "models/review-fixture"}
    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    monkeypatch.setattr(doctor, "missing_requirements", lambda _: [])
    monkeypatch.setattr(doctor, "resolve_node_tools", lambda: doctor.NodeTools("node", "npm", "v22.12.0"))
    monkeypatch.setattr(config, "get_config", lambda: settings)
    monkeypatch.setattr(config, "resolve_path", lambda path: tmp_path / path)
    monkeypatch.setattr(document_guard, "verified_file", lambda *args: pytest.fail("doctor hashed model files"))
    frontend = tmp_path / "frontend/node_modules/.package-lock.json"
    frontend.parent.mkdir(parents=True)
    frontend.touch()
    for key in ("deberta", "qwen_guard"):
        model = tmp_path / settings["models"][key]["path"]
        model.mkdir(parents=True)
        for name in ("config.json", "tokenizer_config.json", "weights.safetensors"):
            (model / name).touch()
    if review_ready:
        for filename in document_guard.RUNTIME_FILES:
            path = tmp_path / settings["models"]["document_guard"]["path"] / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
    result = doctor.diagnose()
    assert result["ok"] is True
    warnings = {row["name"] for row in result["checks"] if row.get("warning")}
    assert warnings == {"detect_path", "asr_path"} | ({"文档复核模型"} if review_ready is False else set())
    review = [row for row in result["checks"] if row["name"] == "文档复核模型"]
    assert [row["ok"] for row in review] == ([] if review_ready is None else [review_ready])
    serve.run(check=True)
    output = capsys.readouterr().out
    assert "[警告] detect_path：评测数据尚未准备" in output
    assert ("scripts/download_document_guard.py" in output) is (review_ready is False)


def test_node_process_timeout_is_reported_as_missing(monkeypatch):
    monkeypatch.setattr(doctor.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("node", 10)))
    assert doctor.node_version("node") is None


def test_windows_uses_portable_node_when_path_has_no_npm(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "win32")
    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "node" if name == "node" else None)
    monkeypatch.setattr(doctor, "node_version", lambda executable: "v22.12.0")
    monkeypatch.setattr(doctor, "npm_version", lambda tools: "10.9.0" if tools.npm else None)
    directory = tmp_path / ".runtime" / "dev-tools" / "node-v22.12.0-win-x64"
    directory.mkdir(parents=True)
    node = directory / "node.exe"
    npm = directory / "npm.cmd"
    node.touch()
    npm.touch()

    tools = doctor.resolve_node_tools()
    assert (tools.node, tools.npm, tools.version) == (node, npm, "v22.12.0")
    assert Path(tools.environment()["PATH"].split(os.pathsep)[0]) == directory


def test_windows_checks_node_used_by_npm_wrapper(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "win32")
    npm = tmp_path / "npm.cmd"
    actual_node = npm.with_name("node.exe")
    actual_node.touch()
    monkeypatch.setattr(doctor.shutil, "which", lambda name: str(npm) if name == "npm.cmd" else "another-node")
    monkeypatch.setattr(doctor, "node_version", lambda executable: "v22.12.0" if executable == actual_node else "v18.0.0")
    monkeypatch.setattr(doctor, "npm_version", lambda tools: "10.9.0")

    tools = doctor.resolve_node_tools()
    assert tools.node == actual_node and tools.npm == str(npm)
    assert tools.version == "v22.12.0"


def test_windows_falls_back_when_system_npm_command_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "win32")
    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "broken-npm.cmd" if name == "npm.cmd" else "node")
    monkeypatch.setattr(doctor, "node_version", lambda executable: "v22.12.0")
    directory = tmp_path / ".runtime/dev-tools/node-v22.12.0-win-x64"
    directory.mkdir(parents=True)
    node, npm = directory / "node.exe", directory / "npm.cmd"
    node.touch()
    npm.touch()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["shell"] and kwargs["env"]["NPM_CONFIG_LOGS_MAX"] == "0"
        if command[0] == "broken-npm.cmd":
            raise subprocess.CalledProcessError(23, command)
        return SimpleNamespace(stdout="10.9.0\n")

    monkeypatch.setattr(doctor.subprocess, "run", run)
    assert doctor.resolve_node_tools().npm == npm
    assert calls == [["broken-npm.cmd", "--version"], [npm, "--version"]]


def test_duplicate_launcher_preserves_stop_request_and_check_does_not_wait(tmp_path, monkeypatch, capsys):
    runtime = tmp_path / ".runtime"
    monkeypatch.setattr(serve, "ROOT", tmp_path)
    monkeypatch.setattr(serve.bootstrap, "main", lambda: pytest.fail("duplicate launcher ran bootstrap"))
    monkeypatch.setattr(serve, "run_services", lambda _: pytest.fail("duplicate launcher loaded services"))
    monkeypatch.setattr(serve, "diagnose", lambda: {"checks": [], "ok": True})
    with serve.launcher_lock(runtime) as acquired:
        assert acquired
        stop_request = runtime / "stop.request"
        stop_request.write_bytes(b"stop\n")
        serve.run(setup=True)
        assert stop_request.read_bytes() == b"stop\n"
        serve.run(check=True)
    assert "正在启动或已在运行" in capsys.readouterr().out


def test_launcher_holds_lock_through_bootstrap_and_releases_when_services_fail(tmp_path, monkeypatch):
    runtime = tmp_path / ".runtime"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(serve, "ROOT", tmp_path)
    stages = []

    def bootstrap():
        with serve.launcher_lock(runtime) as acquired:
            assert not acquired
        stages.append("bootstrap")
        return 0

    def services(setup):
        with serve.launcher_lock(runtime) as acquired:
            assert not acquired
        stages.append("services")
        raise RuntimeError("test launch failed")

    monkeypatch.setattr(serve.bootstrap, "main", bootstrap)
    monkeypatch.setattr(serve, "run_services", services)
    with pytest.raises(RuntimeError, match="test launch failed"):
        serve.run()
    assert stages == ["bootstrap", "services"]
    with serve.launcher_lock(runtime) as acquired:
        assert acquired


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
    (root / "scripts/serve.py").write_text(
        "import runpy\nfrom pathlib import Path\nrunpy.run_path('scripts/bootstrap.py', run_name='__main__')\n"
        "Path('started').write_text('ok')\n", encoding="utf-8",
    )
    # A stale stop marker must not hide an actual setup failure.
    (root / ".runtime").mkdir()
    (root / ".runtime/stop.request").write_text("old stop", encoding="utf-8")
    command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "start.bat"]
    first = subprocess.run(command, cwd=root, input=b"\n", capture_output=True, timeout=20)
    assert first.returncode == 1 and not (root / "started").exists()
    second = subprocess.run(command, cwd=root, input=b"\n", capture_output=True, timeout=20)
    assert second.returncode == 0 and (root / "started").read_text() == "ok"
    assert interpreter.stat().st_mtime_ns == original
