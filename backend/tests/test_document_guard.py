"""Verify document review with a test tokenizer and a mocked ONNX session."""
from __future__ import annotations

import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, processors

from backend.app.detectors import document_guard
from scripts import download_document_guard


def pin(data: bytes) -> tuple[int, str]:
    return len(data), hashlib.sha256(data).hexdigest()


@pytest.fixture
def local_guard(tmp_path, monkeypatch):
    count = 2300
    vocabulary = {"[UNK]": 0, "[BOS]": 1, "[EOS]": 2}
    vocabulary.update({f"word{i}": i + 3 for i in range(count)})
    tokenizer = Tokenizer(models.WordLevel(vocabulary, unk_token="[UNK]"))
    tokenizer.normalizer = normalizers.Lowercase()
    tokenizer.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    tokenizer.post_processor = processors.TemplateProcessing(
        single="[BOS] $A [EOS]", special_tokens=[("[BOS]", 1), ("[EOS]", 2)],
    )
    tokenizer.enable_truncation(max_length=1024, stride=0)
    tokenizer_path = tmp_path / document_guard.TOKENIZER_FILENAME
    tokenizer.save(str(tokenizer_path))
    model_path = tmp_path / document_guard.MODEL_FILENAME
    model_path.parent.mkdir()
    model_bytes = b"mock ONNX model"
    model_path.write_bytes(model_bytes)
    monkeypatch.setattr(document_guard, "RUNTIME_FILES", {
        document_guard.MODEL_FILENAME: pin(model_bytes), document_guard.TOKENIZER_FILENAME: pin(tokenizer_path.read_bytes()),
    })
    monkeypatch.setattr(document_guard, "_bundles", {})
    inputs = [SimpleNamespace(name=name, type="tensor(int64)") for name in ("input_ids", "attention_mask")]
    loads, windows = [], []
    state = SimpleNamespace(logits=None)

    def inference(path, *, sess_options, providers):
        assert Path(path) == model_path
        loads.append((sess_options.intra_op_num_threads, sess_options.inter_op_num_threads, providers))

        def run(outputs, features):
            assert outputs == ["logits"]
            ids, mask = features["input_ids"], features["attention_mask"]
            assert ids.dtype == mask.dtype == np.int64 and ids.shape == mask.shape
            assert (mask == 1).all() and ids.shape[0] == 1
            windows.append(ids[0].tolist())
            logits = state.logits if state.logits is not None else [[0.0, 2.0]] if count + 2 in ids[0] else [[5.0, 0.0]]
            return [np.asarray(logits)]

        return SimpleNamespace(get_inputs=lambda: inputs, get_outputs=lambda: [SimpleNamespace(name="logits")], run=run)

    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(SessionOptions=SimpleNamespace, InferenceSession=inference))
    config = {"models": {"cpu_threads": 3, "document_guard": {"path": str(tmp_path)}}}
    return SimpleNamespace(config=config, count=count, model_bytes=model_bytes, model_path=model_path, loads=loads, windows=windows, state=state)


def test_document_guard_preserves_normalization_and_scores_entire_document(local_guard):
    text = " ".join(f"WORD{i}" for i in range(local_guard.count))
    result = document_guard.DocumentGuard(local_guard.config).detect(text)
    assert result.status == "ok" and result.layer == "L2_review" and result.is_attack is True
    assert result.score == pytest.approx(0.88079707798)
    assert result.details["window_count"] == 3 and result.details["max_tokens"] == 1024
    assert result.details["repo"] == document_guard.REPO_ID and result.details["revision"] == document_guard.REVISION
    assert local_guard.loads == [(3, 1, ["CPUExecutionProvider"])]

    windows = local_guard.windows
    assert all(ids[0] == 1 and ids[-1] == 2 and len(ids) <= 1024 for ids in windows)
    combined = windows[0][1:-1]
    for previous, current in zip(windows, windows[1:]):
        assert previous[-129:-1] == current[1:129]
        combined.extend(current[129:-1])
    assert combined == list(range(3, local_guard.count + 3))


@pytest.mark.parametrize("logits", [[[0.0, np.nan]], [[np.inf, 0.0]], [[0.0, 0.0, 0.0]]])
def test_document_guard_invalid_logits_do_not_produce_a_verdict(local_guard, logits):
    local_guard.state.logits = logits
    result = document_guard.DocumentGuard(local_guard.config).detect("word0")
    assert result.status == "error" and result.error
    assert result.score is None and result.is_attack is None


def test_document_guard_integrity_failure_is_not_cached(local_guard):
    local_guard.model_path.write_bytes(b"x" * len(local_guard.model_bytes))
    result = document_guard.DocumentGuard(local_guard.config).detect("word0")
    assert result.status == "error" and "校验失败" in result.error
    assert not local_guard.loads

    local_guard.model_path.write_bytes(local_guard.model_bytes)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: document_guard.DocumentGuard(local_guard.config).detect("word0"), range(6)))
    assert len(local_guard.loads) == 1
    assert all(result.status == "ok" and result.is_attack is False for result in results)


def test_download_pins_official_files_and_reuses_valid_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    contents = {"tokenizer.json": b"test tokenizer", "onnx/model_quantized.onnx": b"test model"}
    monkeypatch.setattr(download_document_guard, "FILES", {name: pin(content) for name, content in contents.items()})
    calls = []

    def fetch(**kwargs):
        assert kwargs["repo_id"] == document_guard.REPO_ID and kwargs["revision"] == document_guard.REVISION
        assert kwargs["endpoint"] == "https://huggingface.co" and kwargs["token"] is False
        filename = kwargs["filename"]
        calls.append(filename)
        path = kwargs["local_dir"] / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents[filename])

    monkeypatch.setattr(download_document_guard, "hf_hub_download", fetch)
    manifest = download_document_guard.download(tmp_path)
    assert manifest == download_document_guard.download(tmp_path)
    assert sorted(calls) == sorted(contents)
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8")) == manifest
    assert all((tmp_path / name).read_bytes() == content for name, content in contents.items())


def test_download_rejects_unverified_file_without_replacing_previous_copy(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    filename = "tokenizer.json"
    monkeypatch.setattr(download_document_guard, "FILES", {filename: pin(b"correct")})
    asset = tmp_path / filename
    asset.write_bytes(b"previous copy")
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"previous manifest")

    def fetch(**kwargs):
        staging = kwargs["local_dir"]
        staging.mkdir()
        (staging / filename).write_bytes(b"invalid")

    monkeypatch.setattr(download_document_guard, "hf_hub_download", fetch)
    with pytest.raises(RuntimeError, match="SHA-256 校验失败"):
        download_document_guard.download(tmp_path)
    assert asset.read_bytes() == b"previous copy" and manifest.read_bytes() == b"previous manifest"
