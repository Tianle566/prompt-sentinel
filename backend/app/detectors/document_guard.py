"""Local multilingual second opinion for the document injection check."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import numpy as np

from backend.app.core.config import resolve_path
from backend.app.detectors.runtime import ModelBundle, ModelUnavailable, model_load_lock
from backend.app.schemas import LayerResult

REPO_ID = "Horizon-Labs/prompt-injection-guard-small"
REVISION = "2efc2ed5abecd21eb45c2506d231a65d6e392b85"
DEFAULT_MODEL_PATH = "models/document-injection-guard"
MODEL_FILENAME = "onnx/model_quantized.onnx"
TOKENIZER_FILENAME = "tokenizer.json"
RUNTIME_FILES = {
    MODEL_FILENAME: (268409234, "61cd0741cdbfcc229e32e1de1392f352736d87d1e8b3c2b67ad9836bb7910d5d"),
    TOKENIZER_FILENAME: (34387555, "47834a7dbbb0c4324fe9569fe47955241594a9ee539c9e478755d6fbc51e5f46"),
}
MAX_TOKENS = 1024
OVERLAP_TOKENS = 128
THRESHOLD = 0.1
STANDALONE_THRESHOLD = 0.5

_bundles: dict[tuple[Path, int], ModelBundle] = {}


def verified_file(path: Path, size: int, sha256: str) -> bool:
    if not path.is_file() or path.stat().st_size != size:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == sha256


def _get_bundle(config: dict) -> ModelBundle:
    models = config.get("models", {})
    path = resolve_path(models.get("document_guard", {}).get("path", DEFAULT_MODEL_PATH)).resolve()
    threads = max(1, int(models.get("cpu_threads", 4)))
    key = (path, threads)
    with model_load_lock:
        if key in _bundles:
            return _bundles[key]
        for filename, (size, digest) in RUNTIME_FILES.items():
            if not verified_file(path / filename, size, digest):
                raise ModelUnavailable(f"文档复核文件缺失或校验失败：{filename}，请运行 scripts/download_document_guard.py")

        import onnxruntime as ort
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(str(path / TOKENIZER_FILENAME))
        tokenizer.no_padding()
        tokenizer.enable_truncation(max_length=MAX_TOKENS, stride=OVERLAP_TOKENS, direction="right")
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(str(path / MODEL_FILENAME), sess_options=options, providers=["CPUExecutionProvider"])
        inputs = {value.name: value.type for value in session.get_inputs()}
        if inputs != {"input_ids": "tensor(int64)", "attention_mask": "tensor(int64)"}:
            raise ModelUnavailable("文档复核模型的输入签名无效")
        if [value.name for value in session.get_outputs()] != ["logits"]:
            raise ModelUnavailable("文档复核模型的输出签名无效")
        bundle = ModelBundle(tokenizer=tokenizer, model=session, device="cpu")
        _bundles[key] = bundle
        return bundle


class DocumentGuard:
    def __init__(self, config: dict):
        self.config = config

    def detect(self, text: str, *, threshold: float = THRESHOLD) -> LayerResult:
        started = time.perf_counter()
        details = {
            "repo": REPO_ID,
            "revision": REVISION,
            "window_count": 0,
            "max_tokens": MAX_TOKENS,
            "overlap_tokens": OVERLAP_TOKENS,
            "threshold": threshold,
        }
        try:
            bundle = _get_bundle(self.config)
            with bundle.lock:
                encoding = bundle.tokenizer.encode(text, add_special_tokens=True)
                windows = [encoding, *encoding.overflowing]
                details["window_count"] = len(windows)
                scores = []
                for window in windows:
                    features = {
                        "input_ids": np.asarray([window.ids], dtype=np.int64),
                        "attention_mask": np.asarray([window.attention_mask], dtype=np.int64),
                    }
                    (output,) = bundle.model.run(["logits"], features)
                    logits = np.asarray(output, dtype=np.float64)
                    if logits.shape != (1, 2) or not np.isfinite(logits).all():
                        raise RuntimeError("Invalid document guard logits")
                    weights = np.exp(logits[0] - logits.max())
                    scores.append(float(weights[1] / weights.sum()))
            score = max(scores)
            is_attack = score >= threshold
            return LayerResult(
                layer="L2_review", is_attack=is_attack, score=score,
                categories=["prompt_injection"] if is_attack else [],
                latency_ms=(time.perf_counter() - started) * 1000, details=details,
            )
        except Exception as exc:
            message = str(exc) if isinstance(exc, ModelUnavailable) else f"文档复核失败：{type(exc).__name__}"
            return LayerResult(
                layer="L2_review", status="error", error=message,
                latency_ms=(time.perf_counter() - started) * 1000, details=details,
            )
