"""Canary variant and longest-common-substring leakage checks in linear time."""
from __future__ import annotations

import time

from backend.app.schemas import LayerResult
from backend.app.defense.canary import contains_canary


def longest_common_substring(left: str, right: str) -> int:
    """Length of the exact longest contiguous match using a suffix automaton.

    Unlike a quadratic character matrix this remains practical at the API's
    document limits. It returns only a length, never the matched secret text.
    """
    if not left or not right:
        return 0
    if len(left) > len(right):
        left, right = right, left
    transitions: list[dict[str, int]] = [{}]
    lengths = [0]
    links = [-1]
    last = 0
    for character in left:
        current = len(lengths)
        lengths.append(lengths[last] + 1)
        links.append(0)
        transitions.append({})
        previous = last
        while previous >= 0 and character not in transitions[previous]:
            transitions[previous][character] = current
            previous = links[previous]
        if previous >= 0:
            found = transitions[previous][character]
            if lengths[previous] + 1 == lengths[found]:
                links[current] = found
            else:
                clone = len(lengths)
                lengths.append(lengths[previous] + 1)
                links.append(links[found])
                transitions.append(transitions[found].copy())
                while previous >= 0 and transitions[previous].get(character) == found:
                    transitions[previous][character] = clone
                    previous = links[previous]
                links[found] = links[current] = clone
        last = current
    state = matched = best = 0
    for character in right:
        while state and character not in transitions[state]:
            state = links[state]
            matched = lengths[state]
        if character in transitions[state]:
            state = transitions[state][character]
            matched += 1
            best = max(best, matched)
        else:
            state = matched = 0
    return best


class OutputChecker:
    def __init__(self, config: dict, guard=None):
        self.config = config
        self.guard = guard

    def check(self, output: str, system_prompt: str, canary: str, prompt: str = "", enabled: bool = True) -> LayerResult:
        started = time.perf_counter()
        settings = self.config["layers"]["l5"]
        active = bool(enabled and settings.get("enabled", True))
        leaked = contains_canary(output, canary)
        threshold = int(settings.get("similarity_threshold", 60))
        length = longest_common_substring(output, system_prompt) if active and settings.get("similarity", True) else 0
        categories = []
        if active and settings.get("canary", True) and leaked:
            categories.append("canary_leakage")
        if active and settings.get("similarity", True) and length > threshold:
            categories.append("prompt_leakage")
        details = {"canary_leaked": leaked, "longest_common_substring": length, "similarity_threshold": threshold, "guard_response": bool(active and settings.get("guard_response", False))}
        guard_error = None
        if active and settings.get("guard_response", False) and not categories:
            if self.guard is None:
                guard_error = "Qwen3Guard 回复审核未初始化"
            else:
                checked = self.guard.moderate_response(prompt, output)
                # Only structured moderation labels are retained: raw generation
                # could contain response fragments carrying a canary.
                details["moderation"] = {"status": checked.status, "safety": checked.details.get("safety"), "refusal": checked.details.get("refusal"), "categories": checked.categories, "latency_ms": checked.latency_ms}
                if checked.status == "error":
                    guard_error = checked.error
                elif checked.is_attack:
                    categories.extend(checked.categories or ["unsafe_response"])
        if guard_error:
            return LayerResult(layer="L5", enabled=active, status="error", categories=categories, details=details, error=guard_error, latency_ms=(time.perf_counter() - started) * 1000)
        return LayerResult(layer="L5", enabled=active, status="ok" if active else "disabled", is_attack=bool(categories) if active else None, score=float(bool(categories)) if active else None, categories=list(dict.fromkeys(categories)), details=details, latency_ms=(time.perf_counter() - started) * 1000)
