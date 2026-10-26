from __future__ import annotations

import copy
import time

from backend.app.core.config import get_config
from backend.app.detectors.deberta import DebertaDetector
from backend.app.detectors.fusion import fuse_results
from backend.app.detectors.qwen_guard import QwenGuardDetector
from backend.app.detectors.rules import RuleDetector
from backend.app.schemas import DetectionResult, LayerResult


class DetectionService:
    def __init__(self, config: dict | None = None):
        self.config = copy.deepcopy(config if config is not None else get_config())
        self.rules = RuleDetector(self.config)
        self.deberta = DebertaDetector(self.config)
        self.guard = QwenGuardDetector(self.config)

    def detect(self, text: str) -> DetectionResult:
        started = time.perf_counter()
        results = []
        for name, detector in (("L1", self.rules), ("L2", self.deberta), ("L3", self.guard)):
            if self.config["layers"][name.lower()]["enabled"]:
                results.append(detector.detect(text))
            else:
                results.append(LayerResult.disabled(name))
        decision = fuse_results(results, self.config)
        return DetectionResult(is_attack=decision.is_attack, layer_results=results, latency_ms=(time.perf_counter() - started) * 1000, strategy=self.config["fusion"]["strategy"], reliable=decision.reliable, fusion_score=decision.score)


def detect(text: str) -> DetectionResult:
    return DetectionService().detect(text)
