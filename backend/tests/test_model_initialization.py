"""Cold comparison requests must serialize Transformers initialization."""
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import torch

from backend.app.core.config import get_config
from backend.app.detectors import runtime
from backend.app.llm import target


def test_target_tokenizer_and_detector_do_not_initialize_concurrently(tmp_path, monkeypatch):
    target_path = tmp_path / "target"
    detector_path = tmp_path / "detector"
    for path in (target_path, detector_path):
        path.mkdir()
        (path / "config.json").write_text("{}")
        (path / "tokenizer_config.json").write_text("{}")
    config = get_config()
    config["models"]["target"].update(path=str(target_path), small_path=str(target_path))
    config["models"]["deberta"]["path"] = str(detector_path)
    first_entered = threading.Event()
    release_first = threading.Event()
    detector_started = threading.Event()
    overlap = threading.Event()

    class Tokenizer:
        @staticmethod
        def from_pretrained(path, **kwargs):
            if path == str(target_path):
                first_entered.set()
                assert release_first.wait(5)
            elif first_entered.is_set() and not release_first.is_set():
                overlap.set()
            return object()

    class Model:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            return cls()

        def to(self, *args, **kwargs):
            return self

        def eval(self):
            return self

    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoTokenizer=Tokenizer, AutoModelForCausalLM=Model,
        AutoModelForSequenceClassification=Model,
    ))
    monkeypatch.setattr(runtime, "_bundles", {})
    monkeypatch.setattr(target, "_tokenizers", {})
    monkeypatch.setattr(runtime, "select_device", lambda _: "cpu")
    monkeypatch.setattr(torch, "set_num_threads", lambda _: None)

    def load_detector():
        detector_started.set()
        return runtime.get_bundle(config, "deberta")

    with ThreadPoolExecutor(max_workers=2) as pool:
        tokenizer = pool.submit(target.TargetLLM(config)._load_tokenizer)
        try:
            assert first_entered.wait(5)
            detector = pool.submit(load_detector)
            assert detector_started.wait(5)
            assert not overlap.wait(0.3), "Detector initialized while target tokenizer was still loading"
        finally:
            release_first.set()
        assert tokenizer.result() is not None
        assert detector.result().device == "cpu"
