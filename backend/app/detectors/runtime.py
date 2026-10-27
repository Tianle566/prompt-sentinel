"""Lazy local-only model loading, shared across request policy snapshots.

Model weights are never downloaded here. A failed load is not cached, so installing
the model with download_models.py immediately makes subsequent requests usable.
Locks protect model loading/generation and keep simultaneous CPU requests bounded.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.app.core.config import resolve_path


class ModelUnavailable(RuntimeError):
    pass


def select_device(requested: str = "auto") -> str:
    import torch
    if requested not in ("auto", "cpu", "cuda", "mps"):
        raise ValueError("device must be auto, cpu, cuda, or mps")
    if requested in ("auto", "cuda") and torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if requested in ("auto", "mps") and mps is not None and mps.is_available():
        return "mps"
    return "cpu"


@dataclass
class ModelBundle:
    tokenizer: Any
    model: Any
    device: str
    lock: Any = field(default_factory=threading.RLock)
    cache: Any = field(default_factory=OrderedDict)

    def cached(self, key):
        value = self.cache.get(key)
        if value is not None:
            self.cache.move_to_end(key)
        return value

    def remember(self, key, value):
        self.cache[key] = value
        self.cache.move_to_end(key)
        while len(self.cache) > 4096:
            self.cache.popitem(last=False)


_bundles: dict[tuple[str, str, str], ModelBundle] = {}
# Shared with the target tokenizer: Transformers initializes lazy imports and
# registries while loading, even when the models themselves are different.
model_load_lock = threading.RLock()


def get_bundle(config: dict, name: str) -> ModelBundle:
    import torch

    path = resolve_path(config["models"][name]["path"])
    if not path.is_dir() or not (path / "config.json").is_file():
        raise ModelUnavailable(f"本地模型未安装：{name}；请运行 python scripts/download_models.py")
    device = select_device(config["models"].get("device", "auto"))
    key = (name, str(path.resolve()), device)
    with model_load_lock:
        if key in _bundles:
            return _bundles[key]
        from transformers import AutoModelForCausalLM, AutoModelForSequenceClassification, AutoTokenizer
        torch.set_num_threads(max(1, int(config["models"].get("cpu_threads", 4))))
        try:
            tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True, trust_remote_code=False)
            cls = AutoModelForSequenceClassification if name == "deberta" else AutoModelForCausalLM
            dtype = torch.float32 if device == "cpu" else torch.float16
            model = cls.from_pretrained(str(path), local_files_only=True, trust_remote_code=False, torch_dtype=dtype)
            try:
                model = model.to(device)
            except (RuntimeError, NotImplementedError):
                if device == "cpu":
                    raise
                # Unsupported accelerator kernels/memory can still use the CPU.
                device = "cpu"
                model = model.to(device=device, dtype=torch.float32)
            model.eval()
            bundle = ModelBundle(tokenizer=tokenizer, model=model, device=device)
            _bundles[key] = bundle
            return bundle
        except Exception as exc:
            raise ModelUnavailable(f"本地模型 {name} 加载失败（{type(exc).__name__}）：请检查下载完整性及依赖版本") from exc


def clear_model_caches() -> None:
    """Clear memoized inference, e.g. before a cold latency experiment."""
    with model_load_lock:
        for bundle in _bundles.values():
            with bundle.lock:
                bundle.cache.clear()


def infer_with_cpu_fallback(bundle: ModelBundle, function):
    """Retry accelerator unsupported/OOM failures using the same local weights."""
    import torch
    try:
        return function()
    except (RuntimeError, NotImplementedError):
        if bundle.device == "cpu":
            raise
        bundle.model = bundle.model.to(device="cpu", dtype=torch.float32)
        bundle.device = "cpu"
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        mps = getattr(torch, "mps", None)
        if mps is not None and getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            mps.empty_cache()
        return function()
