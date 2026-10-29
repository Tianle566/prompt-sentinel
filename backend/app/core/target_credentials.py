"""Endpoint-bound target API credentials, separate from shareable configuration."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from backend.app.core import config as configuration

connection_lock = threading.RLock()


class CredentialError(ValueError):
    pass


def normalize_base_url(value: str, provider: str = "openai") -> str:
    value = value.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        if any(character.isspace() or ord(character) < 32 for character in value):
            raise ValueError
    except ValueError:
        raise CredentialError("服务地址须为 HTTP(S) 地址，不能包含用户名、密码、查询参数或片段") from None
    path = parsed.path.rstrip("/")
    if provider == "openai":
        for suffix in ("/chat/completions", "/models"):
            if path.endswith(suffix):
                path = path[:-len(suffix)]
                break
        if not path:
            path = "/v1"
    host = parsed.hostname.lower()
    host = f"[{host}]" if ":" in host else host
    if port is not None and (parsed.scheme, port) not in (("https", 443), ("http", 80)):
        host += f":{port}"
    return urlunsplit((parsed.scheme, host, path, "", ""))


def normalize_api_key(value: str) -> str:
    value = value.strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    if len(value) > 4096 or any(not 33 <= ord(character) <= 126 for character in value):
        raise CredentialError("API Key 须为不含空白和控制字符的可打印英文字符，最多 4096 个字符")
    return value


def credential_path() -> Path:
    # A custom configuration also gets an independent private runtime directory.
    parent = configuration.CONFIG_PATH.resolve().parent
    root = parent.parent if parent.name == "backend" else parent
    return root / ".runtime" / "target-api-key.json"


def read_saved_credential() -> dict | None:
    path = credential_path()
    if not path.exists():
        return None
    try:
        if path.is_symlink() or path.stat().st_size > 32768:
            raise ValueError
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("api_key"), str) or not isinstance(data.get("base_url"), str):
            raise ValueError
        return {"version": 1, "base_url": normalize_base_url(data["base_url"]), "api_key": normalize_api_key(data["api_key"])}
    except (OSError, ValueError, TypeError, AttributeError):
        raise CredentialError("无法读取已保存的 API Key，请重新导入") from None


def write_saved_credential(data: dict | None) -> None:
    path = credential_path()
    if path.is_symlink():
        raise CredentialError("密钥文件路径无效")
    if data is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".target-key-", dir=path.parent)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        Path(temporary).unlink(missing_ok=True)


def credential_for(settings: dict, *, use_saved: bool = True) -> tuple[str, str]:
    with connection_lock:
        saved = read_saved_credential() if use_saved else None
        address = normalize_base_url(settings["base_url"])
        if saved and saved["base_url"] == address and saved["api_key"]:
            return saved["api_key"], "saved"
        value = normalize_api_key(os.environ.get(settings.get("api_key_env", "TARGET_API_KEY"), ""))
        return value, "environment" if value else "none"


def credential_status(settings: dict) -> dict:
    with connection_lock:
        saved = read_saved_credential()
        key, source = credential_for(settings) if settings.get("provider") == "openai" else ("", "none")
        return {"configured": bool(key), "source": source, "saved": bool(saved and saved["api_key"]),
                "saved_base_url": saved["base_url"] if saved else ""}


def saved_secret_values() -> list[str]:
    try:
        saved = read_saved_credential()
        return [saved["api_key"]] if saved and saved["api_key"] else []
    except CredentialError:
        return []
