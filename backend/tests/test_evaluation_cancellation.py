"""Cancellation preserves partial denominators instead of claiming completion."""
import pytest

from backend.app.schemas import DetectionResult, LayerResult
from backend.tests.test_evaluation import synthetic_eval_config
from scripts import run_eval


def test_runner_cancels_between_samples_and_preserves_partial_artifacts(synthetic_eval_config, tmp_path, monkeypatch):
    calls = []
    class Detector:
        def __init__(self, config):
            self.guard = None
        def detect(self, text):
            calls.append(text)
            return DetectionResult(is_attack=False, reliable=True, latency_ms=1, strategy="any", layer_results=[LayerResult(layer=name, enabled=True, status="ok", is_attack=False, score=0, latency_ms=1) for name in ("L1", "L2", "L3")])
    monkeypatch.setattr("backend.app.services.detection.DetectionService", Detector)
    monkeypatch.setattr(run_eval, "ROOT", tmp_path)
    directory = tmp_path / "cancelled-results"
    progress = []
    summary = run_eval.run_evaluation(synthetic_eval_config, experiment="detection", output_dir=directory, cancel_callback=lambda: bool(calls), progress_callback=lambda value, message: progress.append(value))
    assert summary["status"] == "cancelled" and summary["cancelled"] is True
    assert summary["timed_out"] is False
    assert progress[-1] < 100
    assert summary["inference"]["completed"] == len(calls) == 1
    assert summary["inference"]["requested"] == 4
    assert (directory / "summary.json").is_file()
    assert (directory / "detection_predictions.jsonl").is_file()
    assert (directory / "rules_snapshot.yaml").is_file()
    assert all(row["evaluated"] == 1 and row["unknown"] == 3 for row in summary["tables"]["detection"] if row["lang"] == "all")


def test_subnanosecond_budget_expires_even_before_next_clock_tick(synthetic_eval_config, tmp_path, monkeypatch):
    class ForbiddenDetector:
        def __init__(self, config):
            self.guard = None
        def detect(self, text):
            pytest.fail("An expired evaluation budget must not start inference")
    monkeypatch.setattr("backend.app.services.detection.DetectionService", ForbiddenDetector)
    monkeypatch.setattr(run_eval.time, "monotonic_ns", lambda: 123)
    synthetic_eval_config["evaluation"]["time_budget_seconds"] = 1e-12
    summary = run_eval.run_evaluation(synthetic_eval_config, experiment="detection", output_dir=tmp_path / "expired-budget")
    assert summary["status"] == "incomplete" and summary["timed_out"]
    assert summary["inference"]["completed"] == 0
