"""Qwen3Guard moderation following its official Hugging Face model card.

https://huggingface.co/Qwen/Qwen3Guard-Gen-0.6B
The model's own chat template distinguishes a user prompt from a complete
user/assistant pair. Do not add an invented instruction or generation prompt.
"""
from __future__ import annotations

import re
import time

from backend.app.core.config import get_config
from backend.app.detectors.runtime import get_bundle, infer_with_cpu_fallback
from backend.app.schemas import LayerResult

SAFETY_PATTERN = r"Safety: (Safe|Unsafe|Controversial)"
CATEGORY_PATTERN = r"(Violent|Non-violent Illegal Acts|Sexual Content or Sexual Acts|PII|Suicide & Self-Harm|Unethical Acts|Politically Sensitive Topics|Copyright Violation|Jailbreak|None)"
REFUSAL_PATTERN = r"Refusal: (Yes|No)"


def parse_guard_output(content: str, response: bool = False) -> dict:
    """Exact case-sensitive label/category vocabulary from the official card.

    A missing/ambiguous safety label is an inference error, never a Safe result.
    Response moderation additionally requires the model's Refusal field.
    """
    labels = re.findall(SAFETY_PATTERN, content)
    if len(labels) != 1:
        raise ValueError("Qwen3Guard returned missing or ambiguous Safety label")
    categories = list(dict.fromkeys(re.findall(CATEGORY_PATTERN, content)))
    if not categories or not re.search(r"Categories:\s*\S", content):
        raise ValueError("Qwen3Guard returned missing Categories field")
    if "None" in categories and len(categories) > 1:
        raise ValueError("Qwen3Guard returned contradictory Categories")
    if response and "Jailbreak" in categories:
        raise ValueError("Jailbreak is an input-only Qwen3Guard category")
    refusals = re.findall(REFUSAL_PATTERN, content)
    if response and len(refusals) != 1:
        raise ValueError("Qwen3Guard response moderation requires Refusal field")
    return {"safety": labels[0], "categories": categories, "refusal": refusals[0] if refusals else None}


class QwenGuardDetector:
    def __init__(self, config: dict | None = None):
        self.config = config or get_config()

    def _predict(self, bundle, prompt: str, response: str | None):
        import torch
        settings = self.config["layers"]["l3"]
        messages = [{"role": "user", "content": prompt}]
        if response is not None:
            messages.append({"role": "assistant", "content": response})
        rendered = bundle.tokenizer.apply_chat_template(messages, tokenize=False)
        encoded = bundle.tokenizer([rendered], return_tensors="pt")
        tokens = int(encoded["input_ids"].shape[-1])
        # Never silently truncate away an attack at the end of a long document.
        limit = int(settings.get("max_tokens", 4096))
        if tokens > limit:
            raise ValueError(f"Qwen3Guard input exceeds configured {limit} token context")
        encoded = {key: tensor.to(bundle.device) for key, tensor in encoded.items()}
        with torch.inference_mode():
            generated = bundle.model.generate(**encoded, max_new_tokens=int(settings.get("max_new_tokens", 64)), do_sample=False, pad_token_id=bundle.tokenizer.eos_token_id)
        output_ids = generated[0][tokens:].tolist()
        raw = bundle.tokenizer.decode(output_ids, skip_special_tokens=True)
        parsed = parse_guard_output(raw, response=response is not None)
        return {**parsed, "raw_output": raw, "token_count": tokens, "mode": "response" if response is not None else "input"}

    def moderate(self, prompt: str, response: str | None = None) -> LayerResult:
        started = time.perf_counter()
        try:
            bundle = get_bundle(self.config, "qwen_guard")
            settings = self.config["layers"]["l3"]
            key = (prompt, response, int(settings.get("max_tokens", 4096)), int(settings.get("max_new_tokens", 64)))
            use_cache = bool(self.config.get("evaluation", {}).get("inference_cache", True))
            with bundle.lock:
                parsed = bundle.cached(key) if use_cache else None
                cached = parsed is not None
                if parsed is None:
                    parsed = infer_with_cpu_fallback(bundle, lambda: self._predict(bundle, prompt, response))
                    if use_cache:
                        bundle.remember(key, parsed)
            safety = parsed["safety"]
            attack = safety == "Unsafe" or "Jailbreak" in parsed["categories"] or (safety == "Controversial" and settings.get("block_controversial", False))
            # Generative labels are not calibrated probabilities; use a policy
            # indicator for fusion and expose the actual severity separately.
            return LayerResult(layer="L3", is_attack=attack, score=float(attack), categories=[category for category in parsed["categories"] if category != "None"], latency_ms=(time.perf_counter() - started) * 1000, details={**parsed, "cached": cached, "device": bundle.device, "score_kind": "policy_indicator"})
        except Exception as exc:
            if type(exc).__name__ == "ModelUnavailable":
                message = str(exc)
            elif isinstance(exc, ValueError):
                message = str(exc)
            else:
                message = f"Qwen3Guard 推理失败：{type(exc).__name__}"
            return LayerResult(layer="L3", status="error", error=message, latency_ms=(time.perf_counter() - started) * 1000, details={"mode": "response" if response is not None else "input"})

    def detect(self, text: str) -> LayerResult:
        return self.moderate(text)

    def moderate_response(self, prompt: str, response: str) -> LayerResult:
        return self.moderate(prompt, response)


QwenGuard = QwenGuardDetector
