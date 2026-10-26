#!/usr/bin/env python3
"""Download official HF snapshots into models/, optionally import local GGUF into Ollama."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import ROOT, get_config, resolve_path


def download(which="all", import_ollama=False, refresh=False):
    endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
    if endpoint != "https://huggingface.co":
        raise RuntimeError("只允许 Hugging Face 官方源，请移除 HF_ENDPOINT 镜像配置")
    from huggingface_hub import HfApi, hf_hub_download, snapshot_download
    import psutil

    config = get_config()
    api = HfApi(endpoint="https://huggingface.co")
    manifest_path = ROOT / "models" / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"models": {}}
    names = ["deberta", "qwen_guard", "target"] if which == "all" else [which]
    target_path = None
    for name in names:
        tokenizer_info = None
        entry = config["models"][name]
        small = name == "target" and psutil.virtual_memory().total < 16 * 1024**3
        repo = entry["small_repo_id"] if small else entry["repo_id"]
        path = resolve_path(entry["small_path"] if small else entry["path"])
        prior = manifest.get("models", {}).get(name, {})
        pin = prior.get("revision") if prior.get("repo_id") == repo and not refresh else None
        info = api.model_info(repo, revision=pin)
        revision = info.sha
        print(f"下载 {name}: {repo}@{revision} → {path}", flush=True)
        if name == "target":
            filename = entry["small_filename"] if small else entry["filename"]
            target_path = Path(hf_hub_download(repo_id=repo, filename=filename, revision=revision, local_dir=path, endpoint="https://huggingface.co"))
            for extra in ("README.md", "LICENSE"):
                hf_hub_download(repo_id=repo, filename=extra, revision=revision, local_dir=path, endpoint="https://huggingface.co")
            tokenizer_repo = entry["small_tokenizer_repo_id"] if small else entry["tokenizer_repo_id"]
            old_tokenizer = prior.get("tokenizer", {})
            tokenizer_pin = old_tokenizer.get("revision") if old_tokenizer.get("repo_id") == tokenizer_repo and not refresh else None
            tokenizer_revision = api.model_info(tokenizer_repo, revision=tokenizer_pin).sha
            snapshot_download(repo_id=tokenizer_repo, revision=tokenizer_revision, local_dir=path, endpoint="https://huggingface.co", allow_patterns=["tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt", "chat_template.jinja"], max_workers=4)
            tokenizer_info = {"repo_id": tokenizer_repo, "revision": tokenizer_revision, "purpose": "exact local context length check; no additional model weights"}
        else:
            snapshot_download(repo_id=repo, revision=revision, local_dir=path, endpoint="https://huggingface.co", allow_patterns=["*.json", "*.safetensors", "*.model", "*.txt", "*.jinja", "README.md", "LICENSE"], ignore_patterns=["onnx/*", "openvino/*", "tf_model*", "pytorch_model.bin"], max_workers=4)
        files = []
        for file in sorted(path.rglob("*")):
            if not file.is_file() or ".cache" in file.parts:
                continue
            digest = hashlib.sha256()
            with file.open("rb") as stream:
                for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                    digest.update(chunk)
            files.append({"path": str(file.relative_to(ROOT)), "bytes": file.stat().st_size, "sha256": digest.hexdigest()})
        from filelock import FileLock
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(manifest_path.with_suffix(".lock"))):
            manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"models": {}}
            manifest["models"][name] = {"repo_id": repo, "revision": revision, "source": "https://huggingface.co", "files": files}
            if tokenizer_info:
                manifest["models"][name]["tokenizer"] = tokenizer_info
            manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
            temporary = manifest_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
            temporary.replace(manifest_path)
        print(f"已完成 {name}: {len(files)} 个文件", flush=True)
    if import_ollama:
        import_local_target(config)
    return manifest


def import_local_target(config=None, ollama_path=None):
    """Offline import of a downloaded GGUF into the configured loopback server."""
    import psutil
    from urllib.parse import urlparse
    config = config or get_config()
    entry = config["models"]["target"]
    small = psutil.virtual_memory().total < 16 * 1024**3
    target_path = resolve_path(entry["small_path"] if small else entry["path"]) / (entry["small_filename"] if small else entry["filename"])
    if not target_path.is_file():
        raise FileNotFoundError(target_path)
    binary = "ollama.exe" if os.name == "nt" else "ollama"
    ollama = ollama_path or shutil.which(binary) or str(ROOT / ".runtime" / "ollama" / binary)
    if not Path(ollama).exists() and (ROOT / ".runtime" / "ollama" / "bin" / binary).exists():
        ollama = str(ROOT / ".runtime" / "ollama" / "bin" / binary)
    address = urlparse(config["target"]["base_url"])
    if address.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("本地模型仅导入本机 Ollama")
    modelfile = target_path.parent / "Modelfile"
    modelfile.write_text(f'FROM "{target_path}"\nPARAMETER num_ctx {config["target"]["context_length"]}\nPARAMETER temperature {config["target"]["temperature"]}\n', encoding="utf-8")
    model = config["target"]["small_model"] if small else config["target"]["model"]
    env = {**os.environ, "OLLAMA_MODELS": str(ROOT / "models" / "ollama"), "OLLAMA_HOST": config["target"]["base_url"]}
    subprocess.run([ollama, "create", model, "-f", str(modelfile)], check=True, env=env)
    print(f"已从本地文件导入 {model}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["all", "deberta", "qwen_guard", "target"], default="all")
    parser.add_argument("--import-ollama", action="store_true")
    parser.add_argument("--import-only", action="store_true", help="Import existing GGUF offline")
    parser.add_argument("--refresh", action="store_true", help="Explicitly update pinned revisions")
    args = parser.parse_args()
    import_local_target() if args.import_only else download(args.only, args.import_ollama, args.refresh)
