"""Process-local session secrets, deliberately excluded from public schemas."""
from __future__ import annotations

import secrets
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass


@dataclass
class SessionSecret:
    canary: str
    accessed_at: float


_sessions: OrderedDict[str, SessionSecret] = OrderedDict()
_lock = threading.RLock()
MAX_SESSIONS = 10000
SESSION_TTL_SECONDS = 24 * 60 * 60


def get_session_canary(session_id: str) -> str:
    """Trusted internal oracle; never expose its return value in API/logs."""
    with _lock:
        now = time.monotonic()
        while _sessions:
            key = next(iter(_sessions))
            if now - _sessions[key].accessed_at <= SESSION_TTL_SECONDS:
                break
            _sessions.popitem(last=False)
        secret = _sessions.get(session_id)
        if secret is None:
            secret = SessionSecret("SENTINEL_CANARY_" + secrets.token_hex(16), now)
            _sessions[session_id] = secret
        secret.accessed_at = now
        _sessions.move_to_end(session_id)
        while len(_sessions) > MAX_SESSIONS:
            _sessions.popitem(last=False)
        return secret.canary


def _canary_pattern(canary: str) -> re.Pattern | None:
    """Match the same secret variants for detection and public redaction.

    Keep exact matching for arbitrary secrets. Session canaries additionally
    expose their entropy when just the 32-character hex body is returned.
    Separator-insensitive matching retains original text spans for redaction.
    """
    if not canary:
        return None
    alternatives = [re.escape(canary)]
    normalized = re.sub(r"[\s_-]", "", canary)
    if normalized:
        alternatives.append("(?i:" + r"[\s_-]*".join(re.escape(char) for char in normalized) + ")")
    standard = re.fullmatch(r"SENTINEL_CANARY_([0-9a-fA-F]{32})", canary)
    if standard:
        alternatives.append("(?i:" + standard.group(1) + ")")
    # Complete variants precede the hex body so redaction consumes the prefix
    # too, rather than leaving a fragment of a transformed session secret.
    return re.compile("|".join(alternatives))


def contains_canary(text: str, canary: str) -> bool:
    pattern = _canary_pattern(canary)
    return bool(pattern and pattern.search(text))


def redact_canary(text: str, canary: str) -> str:
    pattern = _canary_pattern(canary)
    return pattern.sub("[会话秘密已隐藏]", text) if pattern else text


class CanaryManager:
    def get(self, session_id: str) -> str:
        return get_session_canary(session_id)
