"""Conservative, document-only review of otherwise reliable L2-only alarms.

Original detector evidence is retained. A separate pinned multilingual classifier
must clear the complete document AND each originally flagged segment. Missing
models, errors, uncertain scores, or another layer's alarm retain the block.
"""
from __future__ import annotations

import copy
import math
import time

from backend.app.detectors.document_guard import DocumentGuard, THRESHOLD


def review_document(text: str, paragraphs: list[dict], flagged_segments: list[dict], config: dict) -> dict:
    trace = {"status": "skipped", "policy": "multilingual_l2_review_v1", "threshold": THRESHOLD, "checks": []}
    if not config.get("documents", {}).get("review_enabled", False):
        trace["reason"] = "disabled"
        return trace
    layers = config["layers"]
    hardened = all(layers[name].get("enabled") for name in ("l1", "l2", "l3", "l4", "l5"))
    hardened = hardened and all(layers["l4"].get(key) for key in ("spotlighting", "sandwich"))
    hardened = hardened and all(layers["l5"].get(key) for key in ("canary", "similarity"))
    if not hardened or config["fusion"].get("strategy") != "any" or not config["fusion"].get("fail_closed"):
        trace["reason"] = "requires_full_protection"
        return trace
    if not paragraphs or not flagged_segments:
        trace["reason"] = "no_l2_alarm"
        return trace
    for paragraph in paragraphs:
        detection = paragraph["detection"]
        rows = {row["layer"]: row for row in detection["layer_results"]}
        if not detection.get("reliable") or any(
            name not in rows or not rows[name].get("enabled") or rows[name].get("status") != "ok"
            or type(rows[name].get("is_attack")) is not bool
            for name in ("L1", "L2", "L3")
        ):
            trace["reason"] = "incomplete_detection"
            return trace
        if any(rows[name]["is_attack"] for name in ("L1", "L3")):
            trace["reason"] = "other_layer_alarm"
            return trace

    started = time.perf_counter()
    try:
        guard = DocumentGuard(config)
        checks = [{"scope": "document", "text": text}, *[
            {"scope": "segment", **segment} for segment in flagged_segments
        ]]
        seen = {}
        for item in checks:
            content = item["text"]
            if content not in seen:
                seen[content] = guard.detect(content).model_dump(mode="json")
            result = seen[content]
            trace["checks"].append({**{key: value for key, value in item.items() if key != "text"}, "result": result})
            score = result.get("score")
            if result.get("enabled") is not True or result.get("status") != "ok" or type(score) not in (float, int) or not math.isfinite(score) or not 0 <= score <= 1 or type(result.get("is_attack")) is not bool:
                trace.update(status="error", reason="review_unavailable")
                return trace
            if result["is_attack"] or score >= THRESHOLD:
                trace.update(status="retained", reason="review_did_not_clear")
                return trace

        # Change effective document decisions only after every check succeeded.
        # Keep the raw L2 scores and all segment results available for inspection.
        updated = copy.deepcopy(paragraphs)
        for paragraph in updated:
            original = paragraph["detection"]
            if not any(row["layer"] == "L2" and row["is_attack"] for row in original["layer_results"]):
                continue
            paragraph["original_detection"] = original
            effective = copy.deepcopy(original)
            for row in effective["layer_results"]:
                if row["layer"] == "L2":
                    row["details"]["document_review"] = "allowed"
                    row["details"]["original_is_attack"] = row["is_attack"]
                    row["details"]["original_categories"] = row["categories"]
                    row["is_attack"] = False
                    row["categories"] = []
            effective.update(is_attack=False, fusion_score=0.0)
            paragraph.update(detection=effective, is_attack=False)
        paragraphs[:] = updated
        trace.update(status="allowed", reason="all_document_and_flagged_segments_cleared")
        return trace
    except Exception as exc:
        trace.update(status="error", reason="review_unavailable", error=f"文档复核未完成（{type(exc).__name__}），维持原拦截。")
        return trace
    finally:
        trace["latency_ms"] = (time.perf_counter() - started) * 1000
