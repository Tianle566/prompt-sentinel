#!/usr/bin/env python3
"""Audit real completed outputs, improve figure readability, and publish them locally.

No target replies or experimental scores are fabricated or regenerated here.
Response-moderation oracles are independently replayed on saved output text.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def finalize(directory="results", import_web=True):
    from backend.app.core.config import resolve_path
    from backend.app.services.evaluation import audit_attack_records, load_samples
    from scripts.run_eval import _human_review, _plots_detection, _write_csv
    from scripts.audit_results import audit
    source = resolve_path(directory)
    summary_path = source / "summary.json"
    summary = json.loads(summary_path.read_text())
    if summary["status"] != "completed" or summary["errors"] or summary["timed_out"]:
        raise ValueError("实验尚未完整完成；保留实际状态，不可标为完成")
    if (source / "ai_review.csv").exists():
        raise ValueError("已有独立 AI 复核，拒绝重新抽样；请分别运行 audit_results.py 与 import_results.py")
    original = source / "human_review.csv"
    if original.exists():
        with original.open(encoding="utf-8-sig", newline="") as stream:
            if any(any(str(row.get(key, "")).strip() for key in ("human_success", "reviewer", "notes")) for row in csv.DictReader(stream)):
                raise ValueError("human_review.csv 已有复核标注，拒绝覆盖；请保留标注并分别运行 audit_results.py 与 import_results.py")
    started = time.monotonic()
    print("复核保存的真实回复和自动判据，不重新生成目标模型输出", flush=True)
    oracle = audit_attack_records(source, progress_callback=lambda percent, message: print(f"[{percent:5.1f}%] {message}", flush=True))
    if oracle["status"] != "verified" or oracle["mismatches"]:
        raise ValueError("独立自动判据复核存在差异，请检查 oracle_audit_summary.json")
    config = json.loads((source / "config_snapshot.json").read_text())
    summary = json.loads(summary_path.read_text())
    ids = set(summary["data_scope"]["detection_ids"])
    samples = [row for row in load_samples("detect", config) if row["id"] in ids]
    predictions = {row["id"]: row["result"] for row in (json.loads(line) for line in (source / "detection_predictions.jsonl").read_text().splitlines() if line.strip())}
    _plots_detection(source, summary["tables"]["detection"], samples, predictions)
    # Retain the exact original worksheet from the run as provenance, and prepare
    # the requested 50 checks on the actual model-judged unsafe-response oracle.
    archived = source / "human_review_uniform.csv"
    if original.exists() and not archived.exists():
        shutil.copy2(original, archived)
    records = [json.loads(line) for line in (source / "asr_responses.jsonl").read_text().splitlines() if line.strip()]
    review = _human_review(records, load_samples("asr", config), int(config["evaluation"].get("human_review_count", 50)), int(config["evaluation"]["seed"]))
    _write_csv(original, review)
    summary["human_review"] = {"worksheet_count": len(review), "model_judged_output_count": sum(row["review_scope"] == "model_response_safety" for row in review), "seed": config["evaluation"]["seed"], "human_completed": False, "scope": "Prefer actual unblocked replies judged by Qwen3Guard; human labels remain empty"}
    names = {"config_snapshot.json", "detection_predictions.jsonl", "asr_responses.jsonl", "summary.json", "inference_identity.json", "overhead_probes.json", "human_review.csv", "human_review_uniform.csv", "oracle_audit.jsonl", "oracle_audit_summary.json", "independent_audit.json"}
    names.update(path.name for path in source.glob("experiment*") if path.is_file())
    summary["artifacts"] = sorted(name for name in names if (source / name).is_file() or name == "independent_audit.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print("从原始输入预测、真实回复独立核对全部表格与图", flush=True)
    independent = audit(source)
    job_id = None
    if import_web:
        from scripts.import_results import import_results
        job_id = import_results(source)
    report = {"status": "verified", "oracle_audit": {key: oracle.get(key) for key in ("status", "records", "matches", "unknown", "response_moderations", "elapsed_seconds")}, "independent_checks": independent["checks_passed"], "elapsed_seconds": time.monotonic() - started, "evaluation_job_id": job_id, "human_review": summary["human_review"]}
    (source / "finalization_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default="results")
    parser.add_argument("--no-web", action="store_true")
    args = parser.parse_args()
    finalize(args.directory, not args.no_web)
