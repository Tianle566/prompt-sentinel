"""Reserve separate verification reports without replacing historical evidence."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def require_unfrozen_path(path: Path, *roots: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    resolved = path.resolve()
    for root in roots:
        frozen = root.resolve() / "data" / "frozen"
        if absolute.is_relative_to(frozen) or resolved.is_relative_to(frozen.resolve()):
            raise ValueError(f"冻结语料目录禁止写入：{path}")
    return resolved


def prepare_report_path(root: Path, output_dir: str | Path | None, kind: str, filename: str) -> Path:
    if output_dir is None:
        parent = root / "results"
        parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = Path(tempfile.mkdtemp(prefix=f"{kind}_{stamp}_", dir=parent))
    else:
        destination = Path(output_dir)
        if not destination.is_absolute():
            destination = root / destination
        destination.mkdir(parents=True, exist_ok=True)
    report = destination / filename
    if report.exists() or report.is_symlink():
        raise FileExistsError(f"Verification report already exists: {report}. Choose a new --output-dir.")
    return report


def write_report(path: Path, report: dict) -> None:
    content = json.dumps(report, ensure_ascii=False, indent=2)
    # Exclusive creation also protects against concurrent verification processes.
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)
