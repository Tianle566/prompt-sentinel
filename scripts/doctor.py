#!/usr/bin/env python3
"""Read-only, offline readiness checks; never install, load models or change data."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
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


def node_version() -> str | None:
    executable = shutil.which("node")
    if not executable:
        return None
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=10, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def diagnose() -> dict:
    checks = []

    def add(name, ok, detail, remedy=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "remedy": remedy if not ok else ""})

    add("Python", sys.version_info[:2] == (3, 11), sys.version.split()[0], "安装 Python 3.11，并使用项目 .venv 运行检查。")
    missing = missing_requirements(ROOT / "backend" / "requirements.txt")
    add("Python依赖", not missing, "依赖版本满足要求" if not missing else ", ".join(missing), "重新运行 start.bat 或 ./start.sh，启动器会补齐依赖。")
    version = node_version()
    add("Node.js", version and supported_node(version), version or "未找到可用 Node.js", "安装 Node.js 20.19+ 或 22.12+，重新打开终端。")
    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    add("npm", npm is not None, "已找到" if npm else "未找到", "安装包含 npm 的 Node.js。")
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
    for key in ("detect_path", "asr_path"):
        present = resolve_path(config["data"][key]).is_file()
        add(key, present, "数据集存在" if present else "数据集缺失", "运行启动脚本完成数据准备。")
    return {"ok": all(row["ok"] for row in checks), "checks": checks, "scope": "离线静态检查；不代表真实推理或完整功能验证"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print a structured report without local secrets")
    args = parser.parse_args()
    result = diagnose()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for row in result["checks"]:
            print(f"[{'通过' if row['ok'] else '待处理'}] {row['name']}：{row['detail']}")
            if row["remedy"]:
                print("  处理：" + row["remedy"])
        print(result["scope"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
