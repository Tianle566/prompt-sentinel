"""Run four reproducible experiments against real local inference.

A dataset/config/code/model fingerprint isolates persistent inference caches. All
reported rates exclude unknown outcomes and disclose those exclusions. Incomplete
runs preserve partial artifacts and never claim that the requested run completed.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import inspect
import json
import math
import os
import platform
import psutil
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import get_config, resolve_path
from backend.app.services.evaluation import ensure_local_target, judge_attack, load_samples

EXPERIMENTS = {"1": "detection", "2": "defense", "3": "ablation", "4": "overhead"}


def as_dict(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def file_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stratified_sample(rows: list[dict], limit: int | None, seed: int) -> list[dict]:
    """Round-robin stratum allocation, deterministic within (lang,label,type)."""
    if not limit or limit >= len(rows):
        return list(rows)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["lang"], row["label"], row["attack_type"])].append(row)
    rng = random.Random(seed)
    for group in groups.values():
        rng.shuffle(group)
    selected = []
    keys = sorted(groups)
    while len(selected) < limit:
        progressed = False
        for key in keys:
            if groups[key] and len(selected) < limit:
                selected.append(groups[key].pop())
                progressed = True
        if not progressed:
            break
    return selected


def classification_metrics(labels, predictions, latencies=None) -> dict:
    pairs = [(int(y), int(p)) for y, p in zip(labels, predictions) if p is not None]
    counts = Counter((y, p) for y, p in pairs)
    tn, fp, fn, tp = (counts[(0, 0)], counts[(0, 1)], counts[(1, 0)], counts[(1, 1)])
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return dict(n=len(labels), evaluated=len(pairs), unknown=len(labels) - len(pairs), tp=tp, tn=tn, fp=fp, fn=fn, precision=precision if pairs else None, recall=recall if pairs else None, f1=(2 * precision * recall / (precision + recall) if precision + recall else 0.0) if pairs else None, fpr=fp / (fp + tn) if fp + tn else None, mean_latency_ms=statistics.mean(latencies) if latencies else None)


def _write_csv(path: Path, rows: list[dict], fields: list[str] | None = None):
    fields = fields or list(dict.fromkeys(key for row in rows for key in row))
    if not fields:
        fields = ["status"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value for key, value in row.items()})


def _json_write(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n", encoding="utf-8")


def _policy(config: dict, enabled: list[str], strategy: str | None = None) -> dict:
    result = copy.deepcopy(config)
    for layer in ("l1", "l2", "l3", "l4", "l5"):
        result["layers"][layer]["enabled"] = layer in enabled
    if strategy:
        result["fusion"]["strategy"] = strategy
    return result


def _fuse(record: dict, config: dict) -> tuple[bool | None, float, bool]:
    from backend.app.detectors.fusion import fuse_results
    from backend.app.schemas import LayerResult
    layers = []
    latency = 0.0
    for raw in record.get("layer_results", []):
        item = copy.deepcopy(raw)
        item["enabled"] = config["layers"][item["layer"].lower()]["enabled"]
        if not item["enabled"]:
            item.update(status="disabled", is_attack=None, score=None, latency_ms=0)
        elif item.get("status") == "ok":
            latency += item.get("latency_ms", 0)
        layers.append(LayerResult(**item))
    value = fuse_results(layers, config["fusion"])
    # The core fuse function may return a tuple, object, dict, or bool; use its
    # documented public shape while preserving error status independently.
    if isinstance(value, tuple):
        prediction = value[0]
    elif isinstance(value, dict):
        prediction = value.get("is_attack")
    elif hasattr(value, "is_attack"):
        prediction = value.is_attack
    else:
        prediction = value
    reliable = all(item.status == "ok" for item in layers if item.enabled)
    return bool(prediction) if reliable else None, latency, reliable


def _inference_fingerprint(config: dict) -> dict:
    code = {}
    for folder in (ROOT / "backend/app/detectors", ROOT / "backend/app/services"):
        for path in sorted(folder.glob("*.py")):
            if path.name != "evaluation.py":
                code[str(path.relative_to(ROOT))] = file_hash(path)
    models = {}
    for key in ("deberta", "qwen_guard"):
        path = resolve_path(config["models"][key]["path"])
        models[key] = {"path": str(path), "files": [{"name": str(p.relative_to(path)), "size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns} for p in sorted(path.rglob("*")) if p.is_file() and p.suffix in (".json", ".safetensors", ".bin", ".model")]}
    return dict(layers={key: config["layers"][key] for key in ("l1", "l2", "l3")}, models=models, runtime=config["models"], code=code, rules=file_hash(ROOT / "backend/rules.yaml"))


def _detection_object(record: dict, policy: dict):
    from backend.app.schemas import DetectionResult, LayerResult
    prediction, latency, reliable = _fuse(record, policy)
    layers = []
    for raw in record["layer_results"]:
        item = copy.deepcopy(raw)
        item["enabled"] = policy["layers"][item["layer"].lower()]["enabled"]
        if not item["enabled"]:
            item.update(status="disabled", is_attack=None, score=None, latency_ms=0)
        layers.append(LayerResult(**item))
    # On model failure retain the original fail-closed behavior for traffic;
    # detection-performance metrics still mark unreliable samples unknown.
    attack = bool(prediction) if reliable else bool(policy["fusion"].get("fail_closed", True))
    return DetectionResult(is_attack=attack, layer_results=layers, latency_ms=latency, strategy=policy["fusion"]["strategy"], reliable=reliable)


def run_evaluation(config=None, experiment="all", limit=None, asr_limit=None, progress_callback=None, output_dir=None) -> dict:
    config = copy.deepcopy(config or get_config())
    experiment = EXPERIMENTS.get(str(experiment), str(experiment))
    if experiment not in ("all", "detection", "defense", "ablation", "overhead"):
        raise ValueError("experiment must be all/detection/defense/ablation/overhead or 1/2/3/4")
    if limit is not None and limit < 1 or asr_limit is not None and asr_limit < 1:
        raise ValueError("Explicit sample limits must be positive; omit them for configured limits")
    need_asr = experiment in ("all", "defense", "ablation")
    if need_asr or experiment == "overhead":
        ensure_local_target(config)
    from backend.app.services.detection import DetectionService
    from backend.app.services.pipeline import PipelineService
    seed = int(config["evaluation"]["seed"])
    random.seed(seed)
    start = time.monotonic()
    started_wall_ns = time.time_ns()
    budget = float(config["evaluation"].get("time_budget_seconds", 7000))
    directory = resolve_path(output_dir or config["evaluation"]["output_dir"])
    if any((directory / name).exists() for name in ("summary.json", "config_snapshot.json", "asr_responses.jsonl", "detection_predictions.jsonl", "human_review.csv", "ai_review.csv")):
        raise FileExistsError("输出目录已有实验或复核证据；请用 --output-dir 指定新目录，保留原始结果")
    directory.mkdir(parents=True, exist_ok=True)
    cache_dir = ROOT / "results" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    sources = load_samples("detect", config)
    attacks = load_samples("asr", config) if need_asr else []
    detect_limit = limit if limit is not None else config["evaluation"].get("detection_limit", 0)
    attack_limit = asr_limit if asr_limit is not None else config["evaluation"].get("asr_limit", 200)
    detect = stratified_sample(sources, detect_limit, seed)
    asr = stratified_sample(attacks, attack_limit, seed)
    # Defense still needs detector cache for its ASR texts, while detection-only
    # does not instantiate or call a target language model.
    work = {row["id"]: row for row in (detect if experiment != "defense" else [])}
    work.update({row["id"]: row for row in asr})
    inference_config = _policy(config, ["l1", "l2", "l3", "l4", "l5"])
    snapshot = copy.deepcopy(config)
    snapshot.get("auth", {}).clear()
    _json_write(directory / "config_snapshot.json", snapshot)
    identity = _inference_fingerprint(inference_config)
    identity_hash = fingerprint(identity)
    detector = DetectionService(inference_config)
    predictions = {}
    errors = []
    cache_hits = 0
    timed_out = False
    callback = progress_callback or (lambda percent, message: None)
    callback(0, "正在检查数据与本地模型；不会调用第三方攻击目标")

    def remaining():
        return budget <= 0 or time.monotonic() - start < budget

    for number, (identifier, sample) in enumerate(work.items()):
        if not remaining():
            timed_out = True
            break
        key = fingerprint({"identity": identity_hash, "text": sample["text"]})
        cache_path = cache_dir / (key + ".json")
        record = None
        if cache_path.exists():
            try:
                record = json.loads(cache_path.read_text())
                if not record.get("reliable"):
                    record = None
                else:
                    cache_hits += 1
            except (ValueError, OSError):
                record = None
        if record is None:
            try:
                record = as_dict(detector.detect(sample["text"]))
                if record.get("reliable"):
                    _json_write(cache_path, record)
            except Exception as exc:
                errors.append({"phase": "detection", "id": identifier, "error": f"{type(exc).__name__}: {exc}"})
                continue
        predictions[identifier] = record
        for layer in record.get("layer_results", []):
            if layer.get("status") == "error":
                errors.append({"phase": "detection", "id": identifier, "layer": layer["layer"], "error": layer.get("error")})
        callback(5 + 40 * (number + 1) / max(len(work), 1), f"检测推断 {number + 1}/{len(work)}（磁盘缓存 {cache_hits}）")
    raw_records = [{"id": row["id"], "lang": row["lang"], "label": row["label"], "attack_type": row["attack_type"], "result": predictions.get(row["id"])} for row in work.values()]
    with (directory / "detection_predictions.jsonl").open("w", encoding="utf-8") as handle:
        for row in raw_records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    tables = {}
    full = _policy(config, ["l1", "l2", "l3", "l4", "l5"])
    strategies = [("L1", ["l1"], None), ("L2", ["l2"], None), ("L3", ["l3"], None), ("any", ["l1", "l2", "l3"], "any"), ("vote", ["l1", "l2", "l3"], "vote"), ("weighted", ["l1", "l2", "l3"], "weighted")]
    detection_metrics = []
    if experiment in ("all", "detection"):
        for name, enabled, strategy in strategies:
            policy = _policy(config, enabled, strategy)
            for lang in ("zh", "en", "all"):
                rows = [row for row in detect if lang == "all" or row["lang"] == lang]
                outcomes = [_fuse(predictions[row["id"]], policy) if row["id"] in predictions else (None, 0, False) for row in rows]
                result = classification_metrics([row["label"] for row in rows], [x[0] for x in outcomes], [x[1] for x in outcomes if x[2]])
                detection_metrics.append(dict(configuration=name, lang=lang, **result))
        _write_csv(directory / "experiment1_detection.csv", detection_metrics)
        tables["detection"] = detection_metrics
        _plots_detection(directory, detection_metrics, detect, predictions)
    ablation_policies = [("full", full)] + [(f"without_L{number}", _policy(config, [f"l{index}" for index in range(1, 6) if index != number])) for number in range(1, 6)]
    defense_policies = [("none", _policy(config, [])), ("hardening", _policy(config, ["l4"])), ("detection", _policy(config, ["l1", "l2", "l3"])), ("full", full)]
    requested_policies = {}
    if experiment in ("all", "defense"):
        requested_policies.update(defense_policies)
    if experiment in ("all", "ablation"):
        requested_policies.update(ablation_policies)
    asr_records = []
    total_asr = len(requested_policies) * len(asr)
    completed_asr = 0
    for name, policy in requested_policies.items():
        pipeline = PipelineService(policy)
        for sample in asr:
            if not remaining():
                timed_out = True
                break
            record = predictions.get(sample["id"])
            session_id = f"eval_{fingerprint([seed, name, sample['id']])[:24]}"
            started = time.monotonic()
            try:
                kwargs = dict(protected=name != "none", session_id=session_id, original_task=sample.get("original_task"))
                if record is not None:
                    kwargs["detection"] = _detection_object(record, policy)
                elif any(policy["layers"][key]["enabled"] for key in ("l1", "l2", "l3")):
                    raise RuntimeError("Required input detection did not complete within the evaluation budget")
                result = as_dict(pipeline.process(sample["text"], **kwargs))
                guard = getattr(pipeline, "guard", getattr(detector, "guard", None))
                canary = pipeline.get_canary(session_id) if hasattr(pipeline, "get_canary") else None
                oracle_evidence = {}
                success = judge_attack(sample, result.get("output", ""), result, guard, canary, evidence=oracle_evidence)
                error = result.get("error")
                if success is None and not error:
                    error = "Automatic oracle unavailable or moderation inconclusive"
                item = dict(configuration=name, id=sample["id"], attack_type=sample["attack_type"], lang=sample["lang"], oracle=sample.get("oracle", {}).get("type"), oracle_evidence=oracle_evidence, success=success, blocked=result.get("blocked", False), latency_ms=(time.monotonic() - started) * 1000, result=result, error=error)
            except Exception as exc:
                item = dict(configuration=name, id=sample["id"], attack_type=sample["attack_type"], lang=sample["lang"], oracle=sample.get("oracle", {}).get("type"), success=None, blocked=None, latency_ms=(time.monotonic() - started) * 1000, result=None, error=f"{type(exc).__name__}: {exc}")
            if item["error"]:
                errors.append({"phase": "asr", "id": sample["id"], "configuration": name, "error": item["error"]})
            asr_records.append(item)
            completed_asr += 1
            with (directory / "asr_responses.jsonl").open("a" if completed_asr > 1 else "w", encoding="utf-8") as handle:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            callback(45 + 45 * completed_asr / max(total_asr, 1), f"策略测试 {completed_asr}/{total_asr}：{name} / {sample['attack_type']}")
        if timed_out:
            break
    asr_metrics = _asr_metrics(asr_records, requested_policies, asr)
    if experiment in ("all", "defense"):
        defense_metrics = [row for row in asr_metrics if row["configuration"] in dict(defense_policies)]
        _write_csv(directory / "experiment2_defense.csv", defense_metrics)
        _plot_asr(directory / "experiment2_asr.png", defense_metrics)
        tables["defense"] = defense_metrics
    if experiment in ("all", "ablation"):
        ablation_metrics = []
        full_f1 = _metric_policy(detect, predictions, full)["f1"]
        baseline_asr = next((row["asr"] for row in asr_metrics if row["configuration"] == "full" and row["attack_type"] == "all"), None)
        for name, policy in ablation_policies:
            metric = _metric_policy(detect, predictions, policy)
            asr_row = next((row for row in asr_metrics if row["configuration"] == name and row["attack_type"] == "all"), {})
            ablation_metrics.append(dict(configuration=name, **metric, asr=asr_row.get("asr"), asr_evaluated=asr_row.get("evaluated", 0), asr_unknown=asr_row.get("unknown", len(asr)), delta_f1=metric["f1"] - full_f1 if metric["f1"] is not None and full_f1 is not None else None, delta_asr=asr_row["asr"] - baseline_asr if asr_row.get("asr") is not None and baseline_asr is not None else None))
        _write_csv(directory / "experiment3_ablation.csv", ablation_metrics)
        _plot_ablation(directory / "experiment3_ablation.png", ablation_metrics)
        tables["ablation"] = ablation_metrics
    if experiment in ("all", "overhead"):
        # Dedicated uncached benign probes measure end-to-end costs, including
        # L4 and L5 even if all attack samples were stopped at input detection.
        probe_config = copy.deepcopy(full)
        probe_config["evaluation"]["inference_cache"] = False
        probe_pipeline = PipelineService(probe_config)
        probe_candidates = [row for row in detect if row["label"] == 0]
        probe_count = int(config["evaluation"].get("overhead_samples", 5))
        probes = []
        for sample in probe_candidates:
            if len(probes) >= probe_count:
                break
            if not remaining():
                timed_out = True
                break
            result = as_dict(probe_pipeline.process(sample["text"], protected=True, session_id=f"overhead_{seed}_{sample['id']}"))
            probes.append(dict(id=sample["id"], configuration="full", blocked=result.get("blocked"), error=result.get("error"), result=result, latency_ms=result.get("latency_ms", 0)))
            if result.get("error"):
                errors.append({"phase": "overhead", "id": sample["id"], "error": result["error"]})
            callback(92 + 6 * len(probes) / max(probe_count, 1), f"无缓存端到端开销测量 {len(probes)}/{probe_count}")
        _json_write(directory / "overhead_probes.json", probes)
        overhead = _overhead(predictions, probes)
        if any(row["n"] == 0 for row in overhead if row["layer"] in ("L4", "L5", "pipeline_total")):
            errors.append({"phase": "overhead", "error": "No completed uncached probe reached every response layer; missing layer latency is not estimated"})
        _write_csv(directory / "experiment4_overhead.csv", overhead)
        _plot_overhead(directory / "experiment4_overhead.png", overhead)
        tables["overhead"] = overhead
    if asr_records:
        review = _human_review(asr_records, asr, int(config["evaluation"].get("human_review_count", 50)), seed)
        _write_csv(directory / "human_review.csv", review)
    elapsed = time.monotonic() - start
    incomplete_detections = len(work) - len(predictions)
    unreliable = sum(not row.get("reliable", False) for row in predictions.values())
    complete = not timed_out and not errors and not incomplete_detections and not unreliable and completed_asr == total_asr
    summary = dict(schema_version=1, status="completed" if complete else "incomplete", experiment=experiment, seed=seed, elapsed_seconds=elapsed, time_budget_seconds=budget, within_two_hours=elapsed < 7200, timed_out=timed_out, data_scope=dict(detect_available=len(sources), detect_requested=len(detect) if experiment != "defense" else 0, asr_available=len(attacks), asr_requested=len(asr), full_detection_corpus=not detect_limit or detect_limit >= len(sources), full_asr_corpus=not attack_limit or attack_limit >= len(attacks), detection_ids=[row["id"] for row in detect] if experiment != "defense" else [], asr_ids=[row["id"] for row in asr]), inference=dict(requested=len(work), completed=len(predictions), unreliable=unreliable, persistent_cache_hits=cache_hits, fingerprint=identity_hash, asr_requested=total_asr, asr_completed=completed_asr), environment=dict(python=platform.python_version(), platform=platform.platform(), configured_device=config["models"]["device"], observed_detector_devices=sorted({str(layer["details"]["device"]) for record in predictions.values() for layer in record.get("layer_results", []) if layer.get("details", {}).get("device")}), cpu_threads=config["models"].get("cpu_threads"), total_memory_bytes=psutil.virtual_memory().total, target_provider=config["target"]["provider"], target_effective_model=config["target"].get("small_model", "qwen3:0.6b") if config["target"]["provider"] == "ollama" and psutil.virtual_memory().total < 16 * 1024**3 else config["target"]["model"], target_gpu_disabled=config["models"]["device"] == "cpu" and config["target"]["provider"] == "ollama"), dataset_hashes={key: file_hash(resolve_path(config["data"][key])) for key in ("detect_path", "asr_path")}, tables=tables, errors=errors, notes=["All target responses are from actual local inference; no simulated or fabricated metrics.", "Unknown outcomes are excluded from rate denominators and counted separately.", "Persistent detector caches preserve original per-layer inference latency; overhead probes additionally disable inference caching and measure the full pipeline.", "Canary ASR uses the raw-generation leakage boolean before public redaction; protected interceptions are counted as unsuccessful attacks.", "L4/L5 do not change input detection F1; their impact is measured by ASR and response-layer latency.", "human_review.csv is an unannotated worksheet, not completed human review.", "Dataset sampling and model seeds are fixed; cryptographic canaries and spotlighting nonces intentionally remain random, so byte-identical generations across processes are not guaranteed."])
    _json_write(directory / "summary.json", summary)
    _json_write(directory / "inference_identity.json", identity)
    summary["artifacts"] = sorted(path.name for path in directory.iterdir() if path.is_file() and path.stat().st_mtime_ns >= started_wall_ns and path.suffix in (".csv", ".png", ".json", ".jsonl"))
    _json_write(directory / "summary.json", summary)
    callback(100, "评测完成" if complete else "评测保留了部分结果；请查看错误、样本范围与超时说明")
    return summary


def _metric_policy(rows, predictions, policy):
    values = [_fuse(predictions[row["id"]], policy) if row["id"] in predictions else (None, 0, False) for row in rows]
    return classification_metrics([row["label"] for row in rows], [value[0] for value in values], [value[1] for value in values if value[2]])


def _asr_metrics(records, policies, samples):
    rows = []
    types = sorted({sample["attack_type"] for sample in samples})
    for name in policies:
        for kind in types + ["all"]:
            expected = [row for row in samples if kind == "all" or row["attack_type"] == kind]
            subset = [row for row in records if row["configuration"] == name and (kind == "all" or row["attack_type"] == kind)]
            known = [row for row in subset if row["success"] is not None]
            successes = sum(row["success"] for row in known)
            rows.append(dict(configuration=name, attack_type=kind, requested=len(expected), completed=len(subset), evaluated=len(known), unknown=len(expected) - len(known), successes=successes, asr=successes / len(known) if known else None, blocked=sum(row["blocked"] is True for row in subset), mean_latency_ms=statistics.mean(row["latency_ms"] for row in subset) if subset else None))
    return rows


def _human_review(records, samples, count, seed):
    indexed = {row["id"]: row for row in samples}
    # Section4.3's human check validates the model-based unsafe-response oracle.
    # Reviewing mostly blocked requests would inflate agreement without actually
    # checking Qwen3Guard. Prefer real unblocked guard-judged replies; small pilot
    # runs can fill the remaining worksheet rows with other explicit criteria.
    preferred = [row for row in records if row.get("oracle") == "guard_unsafe" and not row.get("blocked") and row.get("success") is not None and not row.get("error")]
    rng = random.Random(seed)
    selected = rng.sample(preferred, min(count, len(preferred)))
    remaining = [row for row in records if row not in selected]
    if len(selected) < count:
        selected.extend(rng.sample(remaining, min(count - len(selected), len(remaining))))
    return [dict(configuration=row["configuration"], id=row["id"], attack_type=row["attack_type"], prompt=indexed[row["id"]]["text"], response=(row.get("result") or {}).get("output", ""), oracle=row["oracle"], automatic_success=row["success"], review_scope="model_response_safety" if row in preferred else "other_automatic_criterion", human_success="", reviewer="", notes="") for row in selected]


def _overhead(predictions, records):
    values = defaultdict(list)
    for result in predictions.values():
        for layer in result.get("layer_results", []):
            if layer.get("status") == "ok" and layer.get("enabled"):
                values[layer["layer"]].append(float(layer.get("latency_ms", 0)))
        values["detection_total"].append(float(result.get("latency_ms", 0)))
    # Use full policy only, so repeated ASR policy runs do not overweight layers.
    for row in records:
        if row["configuration"] != "full" or row.get("error"):
            continue
        result = row.get("result") or {}
        values["pipeline_total"].append(float(result.get("latency_ms", row["latency_ms"])))
        for field, name in (("hardening", "L4"), ("output_check", "L5")):
            layer = result.get(field)
            if layer and layer.get("status") == "ok" and layer.get("enabled"):
                values[name].append(float(layer.get("latency_ms", 0)))
        measured = sum(float(item.get("latency_ms", 0)) for item in (result.get("detection", {}).get("layer_results", [])) if item.get("status") == "ok" and item.get("enabled"))
        measured += sum(float((result.get(field) or {}).get("latency_ms", 0)) for field in ("hardening", "output_check"))
        if not row.get("blocked"):
            values["target_and_orchestration"].append(max(0.0, result.get("latency_ms", 0) - measured))
    return [dict(layer=name, n=len(values.get(name, [])), mean_ms=statistics.mean(values[name]) if values.get(name) else None, median_ms=statistics.median(values[name]) if values.get(name) else None, p95_ms=sorted(values[name])[min(len(values[name]) - 1, math.ceil(len(values[name]) * 0.95) - 1)] if values.get(name) else None, source="wall-clock residual after measured layers; includes actual target inference and orchestration" if name == "target_and_orchestration" else "real inference; original detector latency retained across cache reuse") for name in ("L1", "L2", "L3", "L4", "L5", "detection_total", "target_and_orchestration", "pipeline_total")]


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"figure.dpi": 140, "savefig.bbox": "tight", "axes.spines.top": False, "axes.spines.right": False})
    return plt


def _plots_detection(directory, rows, samples, predictions):
    plt = _plt()
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), sharey=True)
    for ax, lang in zip(axes, ("zh", "en")):
        subset = [row for row in rows if row["lang"] == lang]
        ax.bar([row["configuration"] for row in subset], [row["f1"] if row["f1"] is not None else float("nan") for row in subset], color="#197b75")
        ax.set(title=f"Detection F1 / {lang}", ylim=(0, 1), ylabel="F1")
    fig.savefig(directory / "experiment1_f1.png"); plt.close(fig)
    fig, axes = plt.subplots(2, 6, figsize=(18, 6))
    for row in rows:
        if row["lang"] not in ("zh", "en"):
            continue
        i, j = (0 if row["lang"] == "zh" else 1), ["L1", "L2", "L3", "any", "vote", "weighted"].index(row["configuration"])
        ax = axes[i][j]
        matrix = [[row["tn"], row["fp"]], [row["fn"], row["tp"]]]
        ax.imshow(matrix, cmap="Blues")
        for y in range(2):
            for x in range(2):
                ax.text(x, y, matrix[y][x], ha="center", va="center", color="white" if matrix[y][x] > max(max(line) for line in matrix) * .5 else "#172b4d")
        ax.set(title=f"{row['configuration']} / {row['lang']}", xticks=[0, 1], yticks=[0, 1], xlabel="Predicted", ylabel="Actual")
    fig.tight_layout(); fig.savefig(directory / "experiment1_confusion.png"); plt.close(fig)
    from sklearn.metrics import auc, roc_curve
    fig, ax = plt.subplots(figsize=(6, 5))
    roc_rows = []
    for lang in ("zh", "en"):
        pairs = []
        for row in samples:
            if row["lang"] != lang or row["id"] not in predictions:
                continue
            layer = next((x for x in predictions[row["id"]]["layer_results"] if x["layer"] == "L2" and x["status"] == "ok"), None)
            if layer and layer.get("score") is not None:
                pairs.append((row["label"], layer["score"]))
        if len({x[0] for x in pairs}) > 1:
            fpr, tpr, thresholds = roc_curve([x[0] for x in pairs], [x[1] for x in pairs])
            ax.plot(fpr, tpr, label=f"{lang} AUC={auc(fpr,tpr):.3f}")
            roc_rows.extend(dict(lang=lang, fpr=float(f), tpr=float(t), threshold=float(h) if math.isfinite(h) else "infinity") for f, t, h in zip(fpr, tpr, thresholds))
    ax.plot([0, 1], [0, 1], "--", color="gray"); ax.set(xlabel="False positive rate", ylabel="True positive rate", title="L2 DeBERTa ROC")
    if roc_rows:
        ax.legend()
    else:
        ax.text(.5, .4, "Insufficient reliable class scores", ha="center")
    fig.savefig(directory / "experiment1_l2_roc.png"); plt.close(fig)
    _write_csv(directory / "experiment1_l2_roc.csv", roc_rows, ["lang", "fpr", "tpr", "threshold"])


def _plot_asr(path, rows):
    plt = _plt()
    kinds = sorted({row["attack_type"] for row in rows if row["attack_type"] != "all"})
    names = list(dict.fromkeys(row["configuration"] for row in rows))
    fig, ax = plt.subplots(figsize=(12, 5))
    width = .8 / max(len(names), 1)
    for i, name in enumerate(names):
        values = [next((row["asr"] for row in rows if row["configuration"] == name and row["attack_type"] == kind), None) for kind in kinds]
        ax.bar([x + i * width for x in range(len(kinds))], [v if v is not None else float("nan") for v in values], width, label=name)
    ax.set(xticks=[x + width * (len(names) - 1) / 2 for x in range(len(kinds))], xticklabels=kinds, ylabel="Attack success rate", ylim=(0, 1), title="Real local target / automatic attack oracles")
    ax.legend(); fig.savefig(path); plt.close(fig)


def _plot_ablation(path, rows):
    plt = _plt()
    fig, ax = plt.subplots(figsize=(10, 5))
    names = [row["configuration"] for row in rows]
    ax.bar([i - .18 for i in range(len(rows))], [row["f1"] if row["f1"] is not None else float("nan") for row in rows], .36, label="Detection F1")
    ax.bar([i + .18 for i in range(len(rows))], [row["asr"] if row["asr"] is not None else float("nan") for row in rows], .36, label="ASR")
    ax.set(xticks=range(len(rows)), xticklabels=names, ylim=(0, 1), title="Layer ablation"); ax.legend(); fig.savefig(path); plt.close(fig)


def _plot_overhead(path, rows):
    plt = _plt()
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.bar([row["layer"] for row in rows], [row["mean_ms"] if row["mean_ms"] is not None else float("nan") for row in rows], color="#197b75")
    ax.set(ylabel="Mean latency (ms)", title="Measured local inference overhead; missing measurements are blank")
    ax.tick_params(axis="x", rotation=25); fig.savefig(path); plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", default="all", choices=["all", "detection", "defense", "ablation", "overhead", "1", "2", "3", "4"])
    parser.add_argument("--limit", type=int, help="Stratified detection sample limit (default: configuration)")
    parser.add_argument("--asr-limit", type=int, help="Stratified ASR sample limit (default: configuration)")
    parser.add_argument("--output-dir", help="Artifact destination (default: configuration)")
    parser.add_argument("--device", choices=["cpu", "auto", "cuda", "mps"], help="Explicit runtime device; saved in the experiment snapshot")
    args = parser.parse_args()
    config = get_config()
    if args.device:
        config["models"]["device"] = args.device
    result = run_evaluation(config=config, experiment=args.experiment, limit=args.limit, asr_limit=args.asr_limit, output_dir=args.output_dir, progress_callback=lambda p, m: print(f"[{p:5.1f}%] {m}", flush=True))
    print(json.dumps({key: result[key] for key in ("status", "elapsed_seconds", "data_scope", "inference", "artifacts")}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "completed" else 2)


if __name__ == "__main__":
    main()
