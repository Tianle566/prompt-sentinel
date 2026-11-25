#!/usr/bin/env python3
"""Read-only, offline readiness checks; never install, load models or change data."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.bootstrap import missing_requirements


def supported_node(version: str) -> bool:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    if not match:
        return False
    major, minor, patch = map(int, match.groups())
    return (major == 20 and (minor, patch) >= (19, 0)) or (major, minor, patch) >= (22, 12, 0)


def command_version(executable: str | Path, *, env: dict[str, str] | None = None, shell: bool = False) -> str | None:
    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, errors="replace",
            timeout=10, check=True, env=env, shell=shell,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def node_version(executable: str | Path) -> str | None:
    return command_version(executable)


@dataclass(frozen=True)
class NodeTools:
    node: str | Path | None
    npm: str | Path | None
    version: str | None

    def environment(self) -> dict[str, str]:
        env = os.environ.copy()
        if sys.platform == "win32" and self.node:
            env["PATH"] = os.pathsep.join((str(Path(self.node).parent), env.get("PATH", "")))
        return env


def npm_version(tools: NodeTools) -> str | None:
    if not tools.npm:
        return None
    env = tools.environment()
    env.update(NPM_CONFIG_UPDATE_NOTIFIER="false", NPM_CONFIG_LOGS_MAX="0")
    version = command_version(tools.npm, env=env, shell=sys.platform == "win32")
    if version and re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.+-]+)?", version):
        return version
    return None


def resolve_node_tools() -> NodeTools:
    windows = sys.platform == "win32"
    npm = shutil.which("npm.cmd" if windows else "npm")
    node = shutil.which("node")
    if windows and npm:
        sibling = Path(npm).with_name("node.exe")
        if sibling.is_file():
            # The Windows npm wrapper uses its sibling node.exe when present.
            node = sibling
    version = node_version(node) if node else None
    tools = NodeTools(node, npm, version)
    npm_works = npm_version(tools) is not None
    if windows and not (npm_works and version and supported_node(version)):
        for directory in sorted((ROOT / ".runtime" / "dev-tools").glob("node-v*-win-*"), reverse=True):
            portable_node = directory / "node.exe"
            portable_npm = directory / "npm.cmd"
            if portable_node.is_file() and portable_npm.is_file():
                portable_version = node_version(portable_node)
                portable = NodeTools(portable_node, portable_npm, portable_version)
                if portable_version and supported_node(portable_version) and npm_version(portable):
                    return portable
    return tools if npm_works else NodeTools(node, None, version)


def evaluation_checks(config, resolve_path) -> list[dict]:
    checks = []
    for key in ("detect_path", "asr_path"):
        present = resolve_path(config["data"][key]).is_file()
        checks.append({
            "name": key,
            "ok": present,
            "warning": not present,
            "detail": "数据集存在" if present else "评测数据尚未准备",
            "remedy": "需要评测时，用项目 Python 单独运行 scripts/build_dataset.py。" if not present else "",
        })
    return checks


def document_guard_files(config: dict, resolve_path: Callable[[str | Path], Path]) -> tuple[Path, bool]:
    from backend.app.detectors.document_guard import DEFAULT_MODEL_PATH, RUNTIME_FILES

    path = resolve_path(config.get("models", {}).get("document_guard", {}).get("path", DEFAULT_MODEL_PATH))
    return path, all((path / filename).is_file() for filename in RUNTIME_FILES)


def print_checks(checks: list[dict]) -> None:
    remedies = set()
    for row in checks:
        status = "通过" if row["ok"] else "警告" if row.get("warning") else "待处理"
        print(f"[{status}] {row['name']}：{row['detail']}")
        remedy = row["remedy"]
        if remedy and remedy not in remedies:
            print(f"  处理：{remedy}")
            remedies.add(remedy)


def diagnose() -> dict:
    checks = []

    def add(name, ok, detail, remedy=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "remedy": remedy if not ok else ""})

    add("Python", sys.version_info[:2] == (3, 11), sys.version.split()[0], "安装 Python 3.11，并使用项目 .venv 运行检查。")
    missing = missing_requirements(ROOT / "backend" / "requirements.txt")
    add("Python依赖", not missing, "依赖版本满足要求" if not missing else ", ".join(missing), "重新运行 start.bat 或 ./start.sh，启动器会补齐依赖。")
    tools = resolve_node_tools()
    version = tools.version
    add("Node.js", version and supported_node(version), version or "未找到可用 Node.js", "安装 Node.js 20.19+ 或 22.12+，重新打开终端。")
    add("npm", tools.npm is not None, "已验证可运行" if tools.npm else "未找到可用 npm", "安装包含 npm 的 Node.js。")
    frontend = ROOT / "frontend" / "node_modules" / ".package-lock.json"
    add("前端依赖", frontend.is_file(), "已安装" if frontend.is_file() else "尚未安装完整", "运行启动脚本；依赖不完整时会自动重新安装。")
    try:
        from backend.app.core.config import get_config, resolve_path
        config = get_config()
    except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
        add("配置", False, f"配置无法读取或校验（{type(exc).__name__}）", "检查 backend/config.yaml 的字段类型和取值；依赖缺失时先运行启动脚本。")
        return {"ok": False, "checks": checks, "scope": "离线静态检查；不代表真实推理或完整功能验证"}
    add("配置", True, "格式与参数有效")
    for key in ("deberta", "qwen_guard"):
        path = resolve_path(config["models"][key]["path"])
        ok = (path / "config.json").is_file() and (path / "tokenizer_config.json").is_file() and bool(list(path.glob("*.safetensors")))
        add(key, ok, "本地文件齐全" if ok else "模型文件缺失", "联网运行启动脚本，完成官方模型下载。")
    if config.get("documents", {}).get("review_enabled", False):
        try:
            _, present = document_guard_files(config, resolve_path)
        except (AttributeError, ImportError, OSError, TypeError, ValueError):
            present = False
        checks.append({
            "name": "文档复核模型",
            "ok": present,
            "warning": not present,
            "detail": "本地文件齐全" if present else "本地文件缺失或无法检查，应用继续使用原有文档拦截",
            "remedy": "联网运行项目 Python scripts/download_document_guard.py。" if not present else "",
        })
    if config["target"]["provider"] == "ollama":
        try:
            import psutil
            small = psutil.virtual_memory().total < 16 * 1024**3
        except ImportError:
            small = False
        target = config["models"]["target"]
        folder = resolve_path(target["small_path"] if small else target["path"])
        filename = target["small_filename"] if small else target["filename"]
        present = (folder / filename).is_file() and (folder / "tokenizer_config.json").is_file()
        add("目标模型", present, "GGUF与分词器文件齐全" if present else "GGUF或分词器文件缺失", "联网运行启动脚本，下载并导入目标模型。")
        binary = "ollama.exe" if sys.platform == "win32" else "ollama"
        available = bool(shutil.which(binary)) or any((ROOT / ".runtime" / "ollama" / prefix / binary).is_file() for prefix in ("", "bin"))
        add("Ollama", available, "已安装" if available else "尚未安装", "联网运行启动脚本会安装项目专用 Ollama。")
    checks.extend(evaluation_checks(config, resolve_path))
    return {"ok": all(row["ok"] or row.get("warning") for row in checks), "checks": checks, "scope": "离线静态检查；不代表真实推理或完整功能验证"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print a structured report without local secrets")
    args = parser.parse_args()
    result = diagnose()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_checks(result["checks"])
        print(result["scope"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
