"""The official English injection classifier with overlapping token windows."""
from __future__ import annotations

import time
import math

from backend.app.core.config import get_config
from backend.app.detectors.runtime import get_bundle, infer_with_cpu_fallback
from backend.app.schemas import LayerResult


def token_windows(token_ids: list[int], max_tokens: int, overlap: int, special_tokens: int = 2) -> list[list[int]]:
    """Window original token IDs so re-tokenization cannot alter boundaries."""
    capacity = max_tokens - special_tokens
    if capacity <= 0 or not 0 <= overlap < capacity:
        raise ValueError("Sliding window overlap must be smaller than token capacity")
    windows = []
    start = 0
    while True:
        windows.append(token_ids[start:start + capacity])
        if start + capacity >= len(token_ids):
            return windows
        start += capacity - overlap


def injection_label_index(id2label: dict) -> int:
    for index, label in id2label.items():
        if str(label).strip().upper() in ("INJECTION", "PROMPT_INJECTION", "PROMPT INJECTION"):
            return int(index)
    # Do not guess LABEL_1: a different classifier has a different label mapping.
    raise ValueError("Classifier config must explicitly identify the INJECTION label")


class DebertaDetector:
    def __init__(self, config: dict | None = None):
        self.config = config or get_config()

    def _predict(self, bundle, text: str):
        import torch
        settings = self.config["layers"]["l2"]
        tokenizer, model = bundle.tokenizer, bundle.model
        token_ids = tokenizer.encode(text, add_special_tokens=False)
        special = tokenizer.num_special_tokens_to_add(pair=False)
        model_limit = getattr(model.config, "max_position_embeddings", 512)
        max_tokens = min(int(settings.get("max_tokens", 512)), int(model_limit), 512)
        windows = token_windows(token_ids, max_tokens, int(settings.get("stride", 128)), special)
        index = injection_label_index(model.config.id2label)
        batch_size = max(1, int(settings.get("batch_size", 8)))
        scores = []
        for offset in range(0, len(windows), batch_size):
            encoded = [tokenizer.prepare_for_model(ids, add_special_tokens=True, return_attention_mask=True, truncation=False) for ids in windows[offset:offset + batch_size]]
            batch = tokenizer.pad(encoded, padding=True, return_tensors="pt")
            batch = {key: value.to(bundle.device) for key, value in batch.items()}
            with torch.inference_mode():
                logits = model(**batch).logits
                probabilities = torch.softmax(logits.float(), dim=-1)[:, index]
            batch_scores = [float(score) for score in probabilities.cpu().tolist()]
            if not all(math.isfinite(score) and 0 <= score <= 1 for score in batch_scores):
                raise RuntimeError("Classifier returned invalid/non-finite probabilities")
            scores.extend(batch_scores)
        return max(scores), {"window_count": len(windows), "token_count": len(token_ids), "window_scores": scores, "max_tokens": max_tokens, "overlap_tokens": int(settings.get("stride", 128)), "language_scope": "English pretrained classifier; Chinese effectiveness is measured separately"}

    def detect(self, text: str) -> LayerResult:
        started = time.perf_counter()
        try:
            bundle = get_bundle(self.config, "deberta")
            settings = self.config["layers"]["l2"]
            key = (text, int(settings.get("max_tokens", 512)), int(settings.get("stride", 128)))
            use_cache = bool(self.config.get("evaluation", {}).get("inference_cache", True))
            with bundle.lock:
                value = bundle.cached(key) if use_cache else None
                cached = value is not None
                if value is None:
                    value = infer_with_cpu_fallback(bundle, lambda: self._predict(bundle, text))
                    if use_cache:
                        bundle.remember(key, value)
                score, information = value
            details = {**information, "cached": cached, "device": bundle.device, "threshold": float(settings["threshold"])}
            return LayerResult(layer="L2", is_attack=score >= float(settings["threshold"]), score=score, categories=["prompt_injection"] if score >= float(settings["threshold"]) else [], latency_ms=(time.perf_counter() - started) * 1000, details=details)
        except Exception as exc:
            message = str(exc) if type(exc).__name__ == "ModelUnavailable" else f"DeBERTa 推理失败：{type(exc).__name__}"
            return LayerResult(layer="L2", status="error", error=message, latency_ms=(time.perf_counter() - started) * 1000)


DeBERTaDetector = DebertaDetector
