"""Use one classification model alongside the document's rule checks."""

import time

from backend.app.detectors.document_guard import STANDALONE_THRESHOLD, DocumentGuard
from backend.app.detectors.fusion import fuse_results
from backend.app.detectors.rules import RuleDetector
from backend.app.schemas import DetectionResult, LayerResult


class HorizonDocumentDetection:
    def __init__(self, config: dict):
        self.rules = RuleDetector(config) if config["layers"]["l1"]["enabled"] else None
        self.classifier = DocumentGuard(config)

    def detect(self, text: str) -> DetectionResult:
        started = time.perf_counter()
        rules = self.rules.detect(text) if self.rules else LayerResult.disabled("L1")
        classified = self.classifier.detect(text, threshold=STANDALONE_THRESHOLD)
        layers = [rules, classified.model_copy(update={"layer": "L2"})]
        decision = fuse_results(layers, {"strategy": "any", "fail_closed": True})
        return DetectionResult(
            is_attack=decision.is_attack,
            reliable=decision.reliable,
            fusion_score=decision.score,
            layer_results=layers,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
