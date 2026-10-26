from __future__ import annotations

import base64
import re
import time
from pathlib import Path

import yaml

from backend.app.core.config import ROOT, resolve_path
from backend.app.schemas import LayerResult


def _readable_encoding(rule_id: str, value: str) -> bool:
    """Encoding-shaped strings are signals only when they carry readable text."""
    try:
        if rule_id == "BASE64_001":
            decoded = base64.b64decode(value, validate=True)
        else:
            payload = value[2:] if value.lower().startswith("0x") else value.replace("\\x", "").replace("\\X", "")
            decoded = bytes.fromhex(payload)
        text = decoded.decode("utf-8", errors="strict")
        return bool(text) and sum(character.isprintable() for character in text) / len(text) >= 0.8
    except (ValueError, UnicodeDecodeError):
        return False


def _matches(rule_id: str, pattern: re.Pattern, text: str) -> bool:
    if rule_id not in {"BASE64_001", "HEX_001"}:
        return bool(pattern.search(text))
    # A readable base64 segment can be an ordinary URL path. Do not extract a
    # smaller candidate from a URL and mistake that URL for an encoded command.
    urls = list(re.finditer(r"(?:https?://|www\.)[^\s<>\"']+", text, re.I))
    for match in pattern.finditer(text):
        if any(match.start() < url.end() and match.end() > url.start() for url in urls):
            continue
        if _readable_encoding(rule_id, match.group()):
            return True
    return False


class RuleDetector:
    def __init__(self, config: dict | None = None, rules_path: str | Path | None = None):
        self.config = config or {}
        self.path = resolve_path(rules_path or self.config.get("rules_path", "backend/rules.yaml"))
        self._rules = None

    def _load(self):
        if self._rules is None:
            document = yaml.safe_load(self.path.read_text(encoding="utf-8"))
            entries = document["rules"]
            self._rules = [(str(entry["id"]), str(entry["category"]), re.compile(entry["pattern"], re.I | re.M)) for entry in entries if entry.get("enabled", True)]
        return self._rules

    def detect(self, text: str) -> LayerResult:
        started = time.perf_counter()
        try:
            hits = [(rule_id, category) for rule_id, category, pattern in self._load() if _matches(rule_id, pattern, text)]
            return LayerResult(layer="L1", is_attack=bool(hits), score=float(bool(hits)), categories=list(dict.fromkeys(category for _, category in hits)), rule_ids=[rule_id for rule_id, _ in hits], latency_ms=(time.perf_counter() - started) * 1000, details={"rule_count": len(self._rules)})
        except Exception as exc:
            return LayerResult(layer="L1", status="error", error=f"规则库读取失败：{type(exc).__name__}", latency_ms=(time.perf_counter() - started) * 1000)


RulesDetector = RuleDetector
