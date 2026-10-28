#!/usr/bin/env python3
"""Repair an interrupted dependency installation without replacing local state."""
from __future__ import annotations

import importlib.metadata
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def missing_requirements(path: Path) -> list[str]:
    try:
        from packaging.requirements import Requirement
    except ImportError:
        return ["packaging (dependency version checker)"]
    missing = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            version = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(line)
        else:
            if version not in requirement.specifier:
                missing.append(f"{line} (installed: {version})")
    return missing


def main() -> int:
    if sys.version_info[:2] != (3, 11):
        print("项目需要 Python 3.11。请保留并重命名现有 .venv 后重新启动。", file=sys.stderr)
        return 1
    requirements = ROOT / "backend" / "requirements.txt"
    missing = missing_requirements(requirements)
    if not missing:
        return 0
    print("正在补齐或修复 Python 依赖：" + ", ".join(missing), flush=True)
    uv = shutil.which("uv")
    command = [uv, "pip", "install", "--python", sys.executable] if uv else [sys.executable, "-m", "pip", "install"]
    result = subprocess.run([*command, "-r", str(requirements)], cwd=ROOT)
    if result.returncode:
        print("依赖安装未完成。检查网络后重新运行启动脚本即可继续，无需删除项目。", file=sys.stderr)
        return result.returncode
    remaining = missing_requirements(requirements)
    if remaining:
        print("依赖检查未通过：" + ", ".join(remaining), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
