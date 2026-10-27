"""Stop only this checkout's Python, frontend, and local model processes."""
from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    ppid: int
    name: str
    exe: str
    args: tuple[str, ...]
    cwd: str
    created: float


def inside(value: str, directory: Path) -> bool:
    if not value:
        return False
    try:
        path = Path(value)
        return path.is_absolute() and path.resolve().is_relative_to(directory.resolve())
    except (OSError, ValueError, RuntimeError):
        return False


def project_process(process: ProcessInfo, root: Path) -> bool:
    name = process.name.lower().removesuffix(".exe")
    if inside(process.exe, root / ".runtime" / "ollama"):
        return True
    if name in ("python", "pythonw", "python3", "python3.11"):
        if inside(process.exe, root / ".venv"):
            return True
        for argument in process.args[1:]:
            if argument.lower().endswith((".py", ".pyw")):
                path = Path(argument)
                if not path.is_absolute() and process.cwd:
                    path = Path(process.cwd) / path
                if inside(str(path), root):
                    return True
        if inside(process.cwd, root):
            for index, argument in enumerate(process.args[:-1]):
                if argument == "-m" and process.args[index + 1].startswith(("backend.", "scripts.")):
                    return True
                if argument == "-m" and process.args[index + 1] == "uvicorn":
                    return "backend.app.main:app" in process.args
    if name == "node":
        for argument in process.args[1:]:
            if argument.lower().endswith("vite.js"):
                path = Path(argument)
                if not path.is_absolute() and process.cwd:
                    path = Path(process.cwd) / path
                if inside(str(path), root / "frontend" / "node_modules"):
                    return True
        if process.cwd and Path(process.cwd).resolve() == (root / "frontend").resolve():
            npm = any(Path(argument).name == "npm-cli.js" for argument in process.args)
            command = any(argument == "run" and process.args[index + 1] in ("dev", "preview") for index, argument in enumerate(process.args[:-1]))
            return npm and command
    return False


def select_processes(processes: list[ProcessInfo], root: Path, excluded: set[int]) -> list[ProcessInfo]:
    selected = {process.pid for process in processes if process.pid not in excluded and project_process(process, root)}
    while True:
        children = {process.pid for process in processes if process.ppid in selected and process.pid not in excluded}
        if children.issubset(selected):
            break
        selected.update(children)
    return [process for process in processes if process.pid in selected]


def snapshot() -> list[ProcessInfo]:
    records = []
    for process in psutil.process_iter():
        try:
            info = process.as_dict(attrs=["pid", "ppid", "name", "exe", "cmdline", "cwd", "create_time"], ad_value=None)
            records.append(ProcessInfo(info["pid"], info["ppid"] or 0, info["name"] or "", info["exe"] or "", tuple(info["cmdline"] or ()), info["cwd"] or "", info["create_time"] or 0))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return records


def stop_project(dry_run: bool = False, timeout: float = 5) -> int:
    current = psutil.Process(os.getpid())
    excluded = {current.pid, *(parent.pid for parent in current.parents())}

    def remaining():
        return select_processes(snapshot(), ROOT, excluded)

    targets = remaining()
    if not targets:
        print("毕设项目已经停止，没有需要关闭的程序。")
        return 0
    print("仅处理本毕设项目的程序：")
    for process in targets:
        print(f"  PID {process.pid}: {process.name}")
    if dry_run:
        print("预览完成，没有停止任何程序。")
        return 0

    marker = ROOT / ".runtime" / "stop.request"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("stop\n", encoding="utf-8")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not remaining():
            print("模型、Python 后端和前端已停止，内存已释放。")
            return 0
        time.sleep(0.2)

    # Older launchers do not watch the marker. Limit fallback termination to
    # verified project processes, and check creation times against PID reuse.
    errors = []
    for force in (False, True):
        handles = []
        for record in remaining():
            try:
                process = psutil.Process(record.pid)
                if process.create_time() != record.created:
                    continue
                if force:
                    process.kill()
                else:
                    process.terminate()
                handles.append(process)
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied:
                errors.append(record.pid)
        psutil.wait_procs(handles, timeout=3)
        if not remaining():
            print("模型、Python 后端和前端已停止，内存已释放。")
            return 0
    pending = remaining()
    if pending:
        print("仍有项目进程未能停止：" + ", ".join(str(process.pid) for process in pending))
        if errors:
            print("部分进程权限不足，请使用启动项目时的同一 Windows 账号运行。")
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="List project processes without stopping them")
    parser.add_argument("--no-pause", action="store_true", help=argparse.SUPPRESS)
    options = parser.parse_args()
    raise SystemExit(stop_project(options.dry_run))
