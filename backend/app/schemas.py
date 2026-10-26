"""Public, JSON-safe result types shared by the API and evaluation runner."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class LayerResult(BaseModel):
    layer: str
    enabled: bool = True
    is_attack: bool | None = None
    score: float | None = None
    status: Literal["ok", "disabled", "error"] = "ok"
    categories: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    details: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @classmethod
    def disabled(cls, layer: str) -> "LayerResult":
        return cls(layer=layer, enabled=False, status="disabled")


class DetectionResult(BaseModel):
    is_attack: bool
    layer_results: list[LayerResult] = Field(default_factory=list)
    latency_ms: float = 0.0
    strategy: str = "any"
    reliable: bool = True
    fusion_score: float | None = None


class PipelineResult(BaseModel):
    output: str = ""
    blocked: bool = False
    detection: DetectionResult
    output_check: LayerResult | None = None
    hardening: LayerResult | None = None
    latency_ms: float = 0.0
    error: str | None = None
    session_id: str
