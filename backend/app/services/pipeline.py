from __future__ import annotations

import copy
import time
import uuid

from backend.app.core.config import get_config
from backend.app.defense.canary import get_session_canary, redact_canary
from backend.app.defense.hardening import build_messages
from backend.app.defense.output_check import OutputChecker
from backend.app.llm.target import TargetLLM
from backend.app.schemas import DetectionResult, LayerResult, PipelineResult
from backend.app.services.detection import DetectionService


class PipelineService:
    def __init__(self, config: dict | None = None):
        self.config = copy.deepcopy(config if config is not None else get_config())
        self.detector = self.detection_service = DetectionService(self.config)
        self.guard = self.detector.guard
        self.target = TargetLLM(self.config)
        self.output_checker = OutputChecker(self.config, self.guard)

    @staticmethod
    def get_canary(session_id: str) -> str:
        return get_session_canary(session_id)

    def process(self, text: str, protected: bool = True, session_id: str | None = None, original_task: str | None = None, detection: DetectionResult | None = None) -> PipelineResult:
        started = time.perf_counter()
        session_id = session_id or uuid.uuid4().hex
        canary = get_session_canary(session_id)
        if protected:
            detection = detection.model_copy(deep=True) if detection is not None else self.detector.detect(text)
        else:
            detection = DetectionResult(is_attack=False, layer_results=[LayerResult.disabled(name) for name in ("L1", "L2", "L3")], strategy=self.config["fusion"]["strategy"])
        if protected and detection.is_attack:
            unavailable = not detection.reliable
            return PipelineResult(output="检测层不可用，防护模式已拒绝本次请求。请检查模型与配置。" if unavailable else "检测到提示词注入或不安全指令，本次请求已拦截。", blocked=True, detection=detection, latency_ms=(time.perf_counter() - started) * 1000, error="检测未能可靠完成" if unavailable else None, session_id=session_id)
        hardened = build_messages(text, self.config, canary, original_task, enabled=protected)
        try:
            output = self.target.generate(hardened.messages)
        except Exception as exc:
            # Known TargetError messages deliberately exclude request bodies and
            # credentials. Unexpected exception strings may contain secrets.
            error = str(exc) if type(exc).__name__ == "TargetError" else f"目标模型调用失败：{type(exc).__name__}"
            return PipelineResult(output="目标模型暂不可用。", blocked=False, detection=detection, hardening=hardened.result, latency_ms=(time.perf_counter() - started) * 1000, error=error, session_id=session_id)
        checked = self.output_checker.check(output, hardened.system_prompt, canary, prompt=text, enabled=protected)
        blocked = bool(protected and (checked.is_attack or (checked.status == "error" and self.config["fusion"].get("fail_closed", True))))
        error = checked.error if checked.status == "error" else None
        if blocked:
            output = "回复检测未能完成，已阻止输出。" if error else "检测到回复包含系统提示泄露或不安全内容，已阻止输出。"
        return PipelineResult(output=redact_canary(output, canary), blocked=blocked, detection=detection, hardening=hardened.result, output_check=checked, latency_ms=(time.perf_counter() - started) * 1000, error=error, session_id=session_id)
