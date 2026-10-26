"""Unit/contract tests use explicitly synthetic tiny fixtures, never report metrics as experiments."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from backend.app.core.config import ROOT, get_config
from backend.app.schemas import DetectionResult, LayerResult, PipelineResult
from backend.app.services.evaluation import ensure_local_target, judge_attack, load_samples
from scripts.run_eval import classification_metrics, run_evaluation, stratified_sample


def test_metrics_unknown_denominator_and_real_confusion_counts():
    value = classification_metrics([1, 1, 0, 0, 1], [1, 0, 1, 0, None], [1, 2, 3, 4])
    assert (value["tp"], value["fn"], value["fp"], value["tn"]) == (1, 1, 1, 1)
    assert value["f1"] == value["fpr"] == 0.5
    assert value["unknown"] == 1 and value["evaluated"] == 4
    empty = classification_metrics([1], [None])
    assert empty["f1"] is None and empty["precision"] is None


def test_stratification_fixed_seed_covers_all_strata():
    rows = [dict(id=f"{lang}-{label}-{i}", lang=lang, label=label, attack_type="attack" if label else "benign") for lang in ("zh", "en") for label in (0, 1) for i in range(10)]
    selected = stratified_sample(rows, 8, 42)
    assert selected == stratified_sample(rows, 8, 42)
    assert len(selected) == 8
    assert {(row["lang"], row["label"]) for row in selected} == {(l, y) for l in ("zh", "en") for y in (0, 1)}


def test_oracles_preserve_unknown_and_interception_semantics():
    sample = {"text": "synthetic test", "oracle": {"type": "marker", "marker": "PWNED-TEST"}}
    assert judge_attack(sample, "PWNED-TEST") is True
    assert judge_attack(sample, "PWNED-TEST", {"blocked": True}) is False
    assert judge_attack(sample, "", {"error": "target offline"}) is None
    sample["oracle"] = {"type": "canary"}
    assert judge_attack(sample, "[REDACTED]", {"output_check": {"details": {"canary_leaked": True}}}) is True
    assert judge_attack(sample, "[REDACTED]", {"blocked": True, "output_check": {"details": {"canary_leaked": True}}}) is False
    assert judge_attack(sample, "no evidence") is None


def test_unsafe_oracle_requires_actual_guard_safety_level():
    class SyntheticGuard:
        def moderate_response(self, prompt, output):
            return {"status": "ok", "details": {"safety": "Unsafe"}}
    sample = {"text": "synthetic test", "oracle": {"type": "guard_unsafe"}}
    assert judge_attack(sample, "synthetic output", guard=SyntheticGuard()) is True
    assert judge_attack(sample, "synthetic output") is None


@pytest.mark.parametrize("url", ["https://api.example.com/v1", "http://127.0.0.1.evil.test", "http://user:password@localhost:11434", "file:///tmp/model"])
def test_asr_never_calls_remote_target(url):
    config = get_config()
    config["target"]["base_url"] = url
    with pytest.raises(ValueError, match="loopback"):
        ensure_local_target(config)
    with pytest.raises(ValueError, match="loopback"):
        run_evaluation(config, experiment="defense")


@pytest.mark.integration
def test_official_dataset_counts_schema_and_hashes():
    config = get_config()
    detect = load_samples("detect", config)
    asr = load_samples("asr", config)
    manifest = json.loads((ROOT / "data/processed/manifest.json").read_text())
    assert len(detect) == manifest["detect_count"] == 1116
    assert len(asr) == 200
    assert all(row.get("oracle", {}).get("type") in ("marker", "canary", "guard_unsafe") for row in asr)
    assert set(manifest["safety_categories"].values()) == {100}
    assert len(manifest["safety_categories"]) == 6
    for key in ("detect_path", "asr_path"):
        path = ROOT / config["data"][key]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest[key + "_sha256"]
    assert sum(row["source"] == "deepset/prompt-injections:test" for row in detect) == 116


@pytest.fixture
def synthetic_eval_config(tmp_path):
    config = get_config()
    config["evaluation"].update(time_budget_seconds=60, overhead_samples=2, human_review_count=3)
    rows = [dict(id=f"synthetic-{lang}-{label}", text=f"SYNTHETIC_FIXTURE {lang} {label}", lang=lang, label=label, attack_type="goal_hijacking" if label else "benign", source="explicitly synthetic unit-test fixture") for lang in ("zh", "en") for label in (0, 1)]
    attack = [dict(row, oracle={"type": "marker", "marker": "PWNED-TEST"}) for row in rows if row["label"]]
    for name, values in (("detect_path", rows), ("asr_path", attack)):
        path = tmp_path / (name + ".jsonl")
        path.write_text("".join(json.dumps(row) + "\n" for row in values))
        config["data"][name] = str(path)
    return config


def test_four_experiment_artifacts_and_summary_contract(synthetic_eval_config, tmp_path, monkeypatch):
    import backend.app.services.detection as detection_module
    import backend.app.services.pipeline as pipeline_module

    class SyntheticDetector:
        def __init__(self, config):
            self.config = config
            self.guard = None
        def detect(self, text):
            attack = text.endswith(" 1")
            layers = [LayerResult(layer=name, enabled=True, is_attack=attack, score=float(attack), status="ok", latency_ms=0.1, details={"synthetic_test_fixture": True}) for name in ("L1", "L2", "L3")]
            return DetectionResult(is_attack=attack, layer_results=layers, latency_ms=.3, strategy="any", reliable=True)

    class SyntheticPipeline:
        def __init__(self, config):
            self.config = config
            self.guard = None
        def process(self, text, protected=True, session_id=None, original_task=None, detection=None):
            detection = detection or SyntheticDetector(self.config).detect(text)
            active = any(self.config["layers"][x]["enabled"] for x in ("l1", "l2", "l3"))
            blocked = bool(protected and active and detection.is_attack)
            return PipelineResult(output="blocked" if blocked else "PWNED-TEST", blocked=blocked, detection=detection, hardening=LayerResult(layer="L4", enabled=True, is_attack=False, status="ok", latency_ms=.1), output_check=LayerResult(layer="L5", enabled=True, is_attack=False, status="ok", latency_ms=.1), latency_ms=.6, session_id=session_id)

    monkeypatch.setattr(detection_module, "DetectionService", SyntheticDetector)
    monkeypatch.setattr(pipeline_module, "PipelineService", SyntheticPipeline)
    # Deliberately isolate synthetic fixtures from real-inference caches.
    monkeypatch.setattr("scripts.run_eval._inference_fingerprint", lambda config: {"synthetic_test_only": str(tmp_path)})
    output = tmp_path / "artifacts"
    progress = []
    summary = run_evaluation(synthetic_eval_config, output_dir=output, progress_callback=lambda p, m: progress.append(p))
    assert summary["status"] == "completed"
    assert progress[-1] == 100
    for name in ("experiment1_detection.csv", "experiment1_confusion.png", "experiment1_l2_roc.png", "experiment2_defense.csv", "experiment2_asr.png", "experiment3_ablation.csv", "experiment3_ablation.png", "experiment4_overhead.csv", "experiment4_overhead.png", "human_review.csv"):
        assert (output / name).is_file(), name
    assert summary["tables"]["defense"][0]["unknown"] == 0
    assert all(row["f1"] == 1 for row in summary["tables"]["detection"])
    assert "human_review.csv is an unannotated worksheet" in " ".join(summary["notes"])
    from backend.app.services.evaluation import audit_attack_records
    audit = audit_attack_records(output, synthetic_eval_config)
    assert audit["status"] == "verified" and audit["records"] == 18
    assert audit["mismatches"] == [] and audit["unknown"] == 0
    assert (output / "oracle_audit.jsonl").is_file()


def test_timeout_keeps_unknown_metrics_and_never_claims_completion(synthetic_eval_config, tmp_path):
    config = copy.deepcopy(synthetic_eval_config)
    config["evaluation"]["time_budget_seconds"] = 1e-12
    summary = run_evaluation(config, output_dir=tmp_path / "timeout-artifacts")
    assert summary["status"] == "incomplete" and summary["timed_out"] is True
    assert summary["inference"]["completed"] == 0
    assert all(row["f1"] is None for row in summary["tables"]["detection"])
    assert all(row["asr"] is None for row in summary["tables"]["defense"])
    assert all(row["unknown"] == row["n"] for row in summary["tables"]["detection"])


def test_review_sampling_checks_unblocked_guard_replies_before_intercepts():
    from scripts.run_eval import _human_review
    records = [dict(id=f"fixture-{i}", configuration="synthetic", attack_type="role_play", oracle="guard_unsafe", blocked=i >= 60, success=False, result={"output": "explicitly synthetic fixture"}) for i in range(100)]
    samples = [dict(id=row["id"], text="explicitly synthetic fixture") for row in records]
    review = _human_review(records, samples, 50, 42)
    assert len(review) == 50 and review == _human_review(records, samples, 50, 42)
    assert all(int(row["id"].split("-")[1]) < 60 and row["review_scope"] == "model_response_safety" for row in review)
    assert all(row["human_success"] == row["reviewer"] == row["notes"] == "" for row in review)


@pytest.mark.parametrize("annotated_file", ["human_review.csv", "ai_review.csv"])
def test_finalizer_never_overwrites_existing_review(tmp_path, annotated_file):
    from scripts.finalize_results import finalize
    (tmp_path / "summary.json").write_text(json.dumps(dict(status="completed", errors=[], timed_out=False)))
    content = "human_success,reviewer,notes\nFalse,Researcher,Actual annotation\n"
    (tmp_path / annotated_file).write_text(content)
    with pytest.raises(ValueError, match="拒绝"):
        finalize(tmp_path, import_web=False)
    assert (tmp_path / annotated_file).read_text() == content


@pytest.mark.parametrize("evidence", ["summary.json", "asr_responses.jsonl", "ai_review.csv"])
def test_new_evaluation_never_overwrites_previous_evidence(tmp_path, evidence):
    path = tmp_path / evidence
    path.write_text("Previously saved real experiment or review evidence")
    with pytest.raises(FileExistsError, match="--output-dir"):
        run_evaluation(get_config(), output_dir=tmp_path)
    assert path.read_text() == "Previously saved real experiment or review evidence"
    assert not (tmp_path / "config_snapshot.json").exists()
