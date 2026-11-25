#!/usr/bin/env python3
"""Install and verify the fixed multilingual document review model."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from filelock import FileLock
from huggingface_hub import hf_hub_download

from backend.app.core.config import get_config, resolve_path
from backend.app.detectors.document_guard import DEFAULT_MODEL_PATH, REPO_ID, REVISION, RUNTIME_FILES, verified_file

ENDPOINT = "https://huggingface.co"
FILES = {
    **RUNTIME_FILES,
    "config.json": (2031, "d6264037c9aa4b3d821c1c9a0329572033adbdb622788ecca91c3636066d9622"),
    "tokenizer_config.json": (46440, "ea349495764b24570b4560fe2e4a557e5c0a47e6bce782c2409b1d6445cf8633"),
    "special_tokens_map.json": (636, "baec30ea10906f16adb8c18af7a34023002c1746542612b8b41c9f09e1351351"),
    "LICENSE": (11358, "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"),
    "NOTICE": (1566, "5ffe2383027c7510933df2e7055440edde8c96b67b7a58fb477f9632c72b9c14"),
    "README.md": (24991, "875a62fbe80e7536c02f523e85b7c10abd96ecda6f41a9622a2f455338e37e9c"),
    "SHA256SUMS": (690, "362109600cb9d0750e2892890d535229d3616c085b0289e843bb964005931c09"),
}


def download(model_dir: str | Path = DEFAULT_MODEL_PATH) -> dict:
    if os.environ.get("HF_ENDPOINT", ENDPOINT).rstrip("/") != ENDPOINT:
        raise RuntimeError("只允许 Hugging Face 官方源，请移除 HF_ENDPOINT 镜像配置")
    destination = resolve_path(model_dir)
    destination.mkdir(parents=True, exist_ok=True)
    staging = destination / ".download"
    manifest = {"repo_id": REPO_ID, "revision": REVISION, "source": ENDPOINT, "files": []}
    with FileLock(str(destination / "manifest.lock")):
        for filename, (size, digest) in sorted(FILES.items()):
            path = destination / filename
            if not verified_file(path, size, digest):
                pending = staging / filename
                if not verified_file(pending, size, digest):
                    print(f"下载文档复核文件：{filename}", flush=True)
                    hf_hub_download(
                        repo_id=REPO_ID, revision=REVISION, filename=filename, local_dir=staging,
                        endpoint=ENDPOINT, token=False, force_download=pending.exists(),
                    )
                if not verified_file(pending, size, digest):
                    raise RuntimeError(f"文档复核文件大小或 SHA-256 校验失败：{filename}")
                path.parent.mkdir(parents=True, exist_ok=True)
                pending.replace(path)
            manifest["files"].append({"path": filename, "bytes": size, "sha256": digest})
        manifest_path = destination / "manifest.json"
        temporary = manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(manifest_path)
    print(f"已校验文档复核模型 {REPO_ID}@{REVISION}：{destination}", flush=True)
    return manifest


if __name__ == "__main__":
    configured = get_config().get("models", {}).get("document_guard", {})
    download(configured.get("path", DEFAULT_MODEL_PATH))
