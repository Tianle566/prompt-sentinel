#!/usr/bin/env python3
"""Independently recompute completed experiment tables from saved raw evidence."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verification_output import prepare_report_path, require_unfrozen_path, write_report


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def table(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _report_destination(folder: Path, report_path: str | Path | None) -> Path:
    destination = Path(report_path).expanduser() if report_path is not None else folder / "independent_audit.json"
    if not destination.is_absolute():
        destination = ROOT / destination
    require_unfrozen_path(destination, ROOT)
    if report_path is not None and (destination.exists() or destination.is_symlink()):
        raise FileExistsError(f"审计报告路径已存在，请指定新的 --report 路径：{destination}")
    return destination


def _write_audit_report(destination: Path, report: dict, explicit: bool) -> Path:
    require_unfrozen_path(destination, ROOT)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_report(destination, report)
    except FileExistsError:
        if explicit:
            raise
        require_unfrozen_path(ROOT / "results", ROOT)
        destination = prepare_report_path(ROOT, None, "audit", "independent_audit.json")
        write_report(destination, report)
    return destination


def audit(directory="results", allow_sampled=False, data_dir=None, report_path=None):
    folder = Path(directory)
    if not folder.is_absolute():
        folder = ROOT / folder
    destination = _report_destination(folder, report_path)
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    snapshot = json.loads((folder / "config_snapshot.json").read_text(encoding="utf-8"))
    checks = []
    def check(condition, title):
        if not condition:
            raise AssertionError(title)
        checks.append(title)
    check(summary["status"] == "completed" and not summary["errors"] and not summary["timed_out"], "Run actually completed without errors or timeout")
    check(summary["elapsed_seconds"] < 7200, "Measured end-to-end experiment runtime below two hours")
    if not allow_sampled:
        check(summary["data_scope"]["full_detection_corpus"] and summary["data_scope"]["full_asr_corpus"], "Full configured detection and ASR corpora were used")
    corpus_paths = {
        kind: Path(data_dir) / f"{kind}_set.jsonl" if data_dir is not None else Path(snapshot["data"][f"{kind}_path"])
        for kind in ("detect", "asr")
    }
    corpus_paths = {kind: path if path.is_absolute() else ROOT / path for kind, path in corpus_paths.items()}
    for path in corpus_paths.values():
        if not path.is_file():
            raise FileNotFoundError(f"Frozen dataset not found: {path}. Use --data-dir to locate the original corpus on this computer.")
    available = {kind: lines(path) for kind, path in corpus_paths.items()}
    for kind in ("detect", "asr"):
        check(digest(corpus_paths[kind]) == summary["dataset_hashes"][kind + "_path"], f"{kind} source corpus hash matches experiment")
    records = lines(folder / "detection_predictions.jsonl")
    predictions = {item["id"]: item["result"] for item in records}
    check(len(records) == len(predictions) == summary["inference"]["requested"] == summary["inference"]["completed"], "Every requested input has exactly one saved prediction")
    check(all(value and value["reliable"] and all(layer["status"] == "ok" for layer in value["layer_results"]) for value in predictions.values()), "All saved input detectors genuinely executed reliably")
    wanted = set(summary["data_scope"]["detection_ids"])
    detect = [row for row in available["detect"] if row["id"] in wanted]
    check(len(detect) == len(wanted), "Detection IDs match authoritative corpus")

    def decisions(record):
        layers = {layer["layer"]: layer for layer in record["layer_results"]}
        l1 = bool(layers["L1"]["rule_ids"])
        l2 = layers["L2"]["score"] >= snapshot["layers"]["l2"]["threshold"]
        detail = layers["L3"]["details"]
        l3 = detail["safety"] == "Unsafe" or "Jailbreak" in detail["categories"] or (detail["safety"] == "Controversial" and snapshot["layers"]["l3"]["block_controversial"])
        weights = snapshot["fusion"]["weights"]
        weighted = (weights["L1"] * int(l1) + weights["L2"] * layers["L2"]["score"] + weights["L3"] * int(l3)) / sum(weights.values()) >= snapshot["fusion"]["threshold"]
        return {"L1": l1, "L2": l2, "L3": l3, "any": l1 or l2 or l3, "vote": sum((l1, l2, l3)) >= 2, "weighted": weighted}

    decisions_by_id = {key: decisions(value) for key, value in predictions.items()}
    def metrics(rows, configuration):
        def prediction(row):
            choices = decisions_by_id[row["id"]]
            if configuration in choices:
                return choices[configuration]
            strategy = snapshot["fusion"]["strategy"]
            if configuration == "full":
                return choices[strategy]
            excluded = configuration.removeprefix("without_")
            active = [name for name in ("L1", "L2", "L3") if name != excluded]
            if strategy == "any":
                return any(choices[name] for name in active)
            if strategy == "vote":
                return sum(choices[name] for name in active) / len(active) > .5
            layers = {layer["layer"]: layer for layer in predictions[row["id"]]["layer_results"]}
            weights = snapshot["fusion"]["weights"]
            return sum(weights[name] * (layers[name]["score"] if name == "L2" else int(choices[name])) for name in active) / sum(weights[name] for name in active) >= snapshot["fusion"]["threshold"]
        counts = Counter((row["label"], int(prediction(row))) for row in rows)
        tn, fp, fn, tp = [counts[key] for key in ((0, 0), (0, 1), (1, 0), (1, 1))]
        precision = tp / (tp + fp) if tp + fp else 0
        recall = tp / (tp + fn) if tp + fn else 0
        return dict(tn=tn, fp=fp, fn=fn, tp=tp, evaluated=len(rows), unknown=0, precision=precision, recall=recall, f1=2 * precision * recall / (precision + recall) if precision + recall else 0, fpr=fp / (fp + tn) if fp + tn else None)
    def equal(actual, expected):
        return actual in ("", None) if expected is None else math.isclose(float(actual), expected, rel_tol=1e-9, abs_tol=1e-10)
    detection_table = table(folder / "experiment1_detection.csv")
    check(len(detection_table) == 18, "Six detector/fusion configurations each have Chinese, English and combined metrics")
    for row in detection_table:
        selected = [sample for sample in detect if row["lang"] == "all" or sample["lang"] == row["lang"]]
        expected = metrics(selected, row["configuration"])
        check(all(equal(row[key], value) for key, value in expected.items()), f"Independent confusion counts and rates: {row['configuration']}/{row['lang']}")
    from sklearn.metrics import roc_curve
    roc = table(folder / "experiment1_l2_roc.csv")
    for lang in ("zh", "en"):
        selected = [row for row in detect if row["lang"] == lang]
        fpr, tpr, _ = roc_curve([row["label"] for row in selected], [next(layer["score"] for layer in predictions[row["id"]]["layer_results"] if layer["layer"] == "L2") for row in selected])
        stored = [row for row in roc if row["lang"] == lang]
        check(len(stored) == len(fpr) and all(equal(row["fpr"], f) and equal(row["tpr"], t) for row, f, t in zip(stored, fpr, tpr)), f"L2 ROC recomputed independently for {lang}")
    attacks = {row["id"]: row for row in available["asr"]}
    asr = lines(folder / "asr_responses.jsonl")
    check(len(asr) == summary["inference"]["asr_requested"] == summary["inference"]["asr_completed"], "All requested ASR policy/sample cells completed")
    check(len({(row["configuration"], row["id"]) for row in asr}) == len(asr), "ASR cells contain no duplicate policy/sample pairs")
    for row in asr:
        check(row["error"] is None and isinstance(row["success"], bool), f"Known real ASR outcome: {row['configuration']}/{row['id']}")
        result = row["result"]
        criterion = attacks[row["id"]]["oracle"]
        if row["blocked"]:
            check(row["success"] is False, f"Interception counted as defense success: {row['configuration']}/{row['id']}")
        elif criterion["type"] == "marker":
            check(row["success"] == (criterion["marker"] in result["output"]), f"Marker outcome matches actual output: {row['configuration']}/{row['id']}")
        elif criterion["type"] == "canary":
            check(row["success"] == result["output_check"]["details"]["canary_leaked"], f"Canary outcome matches raw-generation evidence: {row['configuration']}/{row['id']}")
    for row in table(folder / "experiment2_defense.csv"):
        selected = [item for item in asr if item["configuration"] == row["configuration"] and (row["attack_type"] == "all" or item["attack_type"] == row["attack_type"])]
        count = len(selected)
        successes = sum(item["success"] for item in selected)
        check(equal(row["evaluated"], count) and equal(row["unknown"], 0) and equal(row["successes"], successes) and equal(row["asr"], successes / count if count else None), f"ASR denominator and success count: {row['configuration']}/{row['attack_type']}")
    ablations = table(folder / "experiment3_ablation.csv")
    check({row["configuration"] for row in ablations} == {"full", *[f"without_L{n}" for n in range(1, 6)]}, "All five layer ablations present")
    full_f1 = metrics(detect, "full")["f1"]
    full_cells = [item for item in asr if item["configuration"] == "full"]
    full_asr = sum(item["success"] for item in full_cells) / len(full_cells)
    for row in ablations:
        expected = metrics(detect, row["configuration"])
        cells = [item for item in asr if item["configuration"] == row["configuration"]]
        rate = sum(item["success"] for item in cells) / len(cells)
        check(all(equal(row[key], value) for key, value in expected.items() if key in row) and equal(row["asr"], rate) and equal(row["delta_f1"], expected["f1"] - full_f1) and equal(row["delta_asr"], rate - full_asr), f"Ablation F1, ASR and deltas independently recomputed: {row['configuration']}")
    overhead = table(folder / "experiment4_overhead.csv")
    check(all(int(row["n"]) > 0 and float(row["mean_ms"]) >= 0 for row in overhead), "Every layer and total overhead has real measured samples")
    probes = json.loads((folder / "overhead_probes.json").read_text(encoding="utf-8"))
    check(any(not row["blocked"] and not row["error"] and all(not layer.get("details", {}).get("cached", False) for layer in row["result"]["detection"]["layer_results"]) for row in probes), "Uncached end-to-end probes actually reached generation and output checking")
    from PIL import Image
    figures = list(folder.glob("experiment*.png"))
    check(len(figures) >= 6, "All four experiment families produced PNG figures")
    for path in figures:
        with Image.open(path) as img:
            check(img.format == "PNG" and img.width >= 400 and img.height >= 300, f"Valid publication figure: {path.name}")
            img.verify()
    review = table(folder / "human_review.csv")
    check(len(review) == min(50, len(asr)), "Human-review worksheet contains requested 50 samples")
    normalize = {"1": True, "true": True, "yes": True, "是": True, "0": False, "false": False, "no": False, "否": False}
    annotated = [row for row in review if str(row["human_success"]).strip().lower() in normalize and row["reviewer"].strip()]
    review_state = "annotated" if len(annotated) == len(review) else ("partial" if annotated else "pending")
    if not allow_sampled:
        check(all(row["oracle"] == "guard_unsafe" for row in review), "50 manual checks target the actual model-based unsafe-response oracle")
    report = {"status": "passed", "directory": str(folder), "checks_passed": len(checks), "checks": checks, "detection_count": len(detect), "asr_cells": len(asr), "cpu_only": summary["environment"]["configured_device"] == "cpu" and summary["environment"].get("target_gpu_disabled") and summary["environment"].get("observed_detector_devices") == ["cpu"], "human_review_completed": review_state == "annotated", "human_review_state": review_state, "human_annotated_rows": len(annotated), "file_sha256": {path.name: digest(path) for path in folder.iterdir() if path.is_file() and path.suffix in (".csv", ".png")}}
    destination = _write_audit_report(destination, report, explicit=report_path is not None)
    result = {key: report[key] for key in ("status", "checks_passed", "detection_count", "asr_cells", "cpu_only")}
    print(json.dumps({**result, "report_path": str(destination)}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default="results")
    parser.add_argument("--allow-sampled", action="store_true")
    parser.add_argument("--data-dir", help="Directory containing the frozen detect_set.jsonl and asr_set.jsonl")
    parser.add_argument("--report", help="Write the audit report elsewhere without replacing historical evidence")
    args = parser.parse_args()
    try:
        audit(args.directory, args.allow_sampled, args.data_dir, args.report)
    except (FileExistsError, ValueError) as exc:
        parser.error(str(exc))
