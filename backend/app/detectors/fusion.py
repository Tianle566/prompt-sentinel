"""Policy fusion keeps model errors distinct from negative classifications."""
from __future__ import annotations

from dataclasses import dataclass

from backend.app.schemas import LayerResult


@dataclass(frozen=True)
class FusionDecision:
    is_attack: bool
    reliable: bool
    score: float | None = None


def fuse_results(results: list[LayerResult], config: dict) -> FusionDecision:
    settings = config.get("fusion", config)
    active = [result for result in results if result.enabled and result.status != "disabled"]
    errors = [result for result in active if result.status != "ok" or result.is_attack is None]
    if errors and settings.get("fail_closed", True):
        return FusionDecision(True, False)
    valid = [result for result in active if result.status == "ok" and result.is_attack is not None]
    if not valid:
        return FusionDecision(False, not errors)
    strategy = settings.get("strategy", "any")
    if strategy == "any":
        score = float(any(result.is_attack for result in valid))
        return FusionDecision(bool(score), not errors, score)
    if strategy == "vote":
        score = sum(bool(result.is_attack) for result in valid) / len(valid)
        return FusionDecision(score > 0.5, not errors, score)
    if strategy == "weighted":
        weights = settings.get("weights", {"L1": 1, "L2": 1, "L3": 1})
        denominator = sum(float(weights.get(result.layer, 0)) for result in valid)
        if denominator <= 0:
            return FusionDecision(bool(settings.get("fail_closed", True)), False)
        score = sum(float(weights.get(result.layer, 0)) * (float(result.score) if result.score is not None else float(bool(result.is_attack))) for result in valid) / denominator
        return FusionDecision(score >= float(settings.get("threshold", 0.5)), not errors, score)
    raise ValueError(f"Unknown fusion strategy: {strategy}")


class FusionDetector:
    def __init__(self, config: dict):
        self.config = config

    def fuse(self, results: list[LayerResult]) -> FusionDecision:
        return fuse_results(results, self.config)
