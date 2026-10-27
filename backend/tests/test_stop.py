"""Process selection must stop the project while preserving other applications."""
from pathlib import Path

from scripts import stop


def record(pid, exe, args=(), cwd="", ppid=0, name="python.exe"):
    return stop.ProcessInfo(pid, ppid, name, str(exe), tuple(map(str, args)), str(cwd), 1.0)


def test_selects_project_services_and_descendants(tmp_path):
    root = tmp_path / "project"
    processes = [
        record(101, root / ".venv/Scripts/python.exe"),
        record(102, tmp_path / "system/python.exe", ppid=101),
        record(103, root / ".runtime/ollama/ollama.exe", name="ollama.exe"),
        record(104, tmp_path / "runner.exe", ppid=103, name="runner.exe"),
        record(105, tmp_path / "node.exe", args=("node", root / "frontend/node_modules/.bin/../vite/bin/vite.js"), name="node.exe"),
        record(106, tmp_path / "esbuild.exe", ppid=105, name="esbuild.exe"),
    ]
    assert {p.pid for p in stop.select_processes(processes, root, set())} == {101, 102, 103, 104, 105, 106}


def test_preserves_other_projects_and_codex_workers(tmp_path):
    root = tmp_path / "project"
    other = tmp_path / "project-other"
    processes = [
        record(201, other / ".venv/Scripts/python.exe", cwd=other),
        record(202, tmp_path / "system/python.exe", args=("python", "-c", "print('hello')"), cwd=root),
        record(203, tmp_path / "node.exe", args=("node", "--eval", f"const root = '{root}';", "--working-dir", root), cwd=root, name="node.exe"),
        record(204, tmp_path / "node.exe", args=("node", other / "frontend/node_modules/vite/bin/vite.js"), cwd=other, name="node.exe"),
        record(205, tmp_path / "Ollama/ollama.exe", args=("ollama", "serve"), cwd=root, name="ollama.exe"),
    ]
    assert stop.select_processes(processes, root, set()) == []


def test_excludes_stop_program_and_its_ancestors(tmp_path):
    root = tmp_path / "project"
    processes = [record(301, root / ".venv/Scripts/python.exe"), record(302, root / ".venv/Scripts/python.exe", ppid=301)]
    assert stop.select_processes(processes, root, {301, 302}) == []


def test_recognizes_relative_launcher_and_project_uvicorn(tmp_path):
    root = tmp_path / "project"
    processes = [
        record(401, tmp_path / "python.exe", args=("python", "scripts/serve.py"), cwd=root),
        record(402, tmp_path / "python.exe", args=("python", "-m", "uvicorn", "backend.app.main:app"), cwd=root),
        record(403, tmp_path / "python.exe", args=("python", "-m", "uvicorn", "other.app:app"), cwd=root),
    ]
    assert {p.pid for p in stop.select_processes(processes, root, set())} == {401, 402}


def test_recognizes_frontend_npm_only_in_frontend_directory(tmp_path):
    root = tmp_path / "project"
    args = ("node", tmp_path / "npm/npm-cli.js", "run", "dev")
    processes = [
        record(501, tmp_path / "node.exe", args=args, cwd=root / "frontend", name="node.exe"),
        record(502, tmp_path / "node.exe", args=args, cwd=tmp_path / "elsewhere", name="node.exe"),
    ]
    assert {p.pid for p in stop.select_processes(processes, root, set())} == {501}


def test_dry_run_does_not_create_shutdown_request(tmp_path, monkeypatch):
    monkeypatch.setattr(stop, "ROOT", tmp_path)
    monkeypatch.setattr(stop, "snapshot", lambda: [record(999999, tmp_path / ".venv/Scripts/python.exe")])
    assert stop.stop_project(dry_run=True) == 0
    assert not (tmp_path / ".runtime/stop.request").exists()


def test_already_stopped_is_successful_and_does_not_change_files(tmp_path, monkeypatch):
    monkeypatch.setattr(stop, "ROOT", tmp_path)
    monkeypatch.setattr(stop, "snapshot", lambda: [])
    assert stop.stop_project() == 0
    assert list(Path(tmp_path).iterdir()) == []


def test_invalid_path_from_another_process_is_ignored(tmp_path):
    assert not stop.inside(str(tmp_path / "invalid\0name.exe"), tmp_path)
