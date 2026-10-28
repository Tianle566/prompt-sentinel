"""Validated, atomic, centrally managed configuration."""
from __future__ import annotations

import copy
import math
import os
import threading
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "backend" / "config.yaml"
_lock = threading.RLock()


def resolve_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def _number(value: Any, name: str, low: float, high: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} 必须在 {low} 到 {high} 之间")


def _integer(value: Any, name: str, low: int, high: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} 必须是 {low} 到 {high} 之间的整数")


def validate_config(config: dict) -> dict:
    if not isinstance(config, dict):
        raise ValueError("配置必须是对象")
    layers = config.get("layers", {})
    for layer in ("l1", "l2", "l3", "l4", "l5"):
        if not isinstance(layers.get(layer), dict) or not isinstance(layers[layer].get("enabled"), bool):
            raise ValueError(f"{layer}.enabled 必须是布尔值")
    _number(layers["l2"]["threshold"], "L2 阈值", 0, 1)
    _integer(layers["l2"]["max_tokens"], "L2 窗口", 16, 512)
    _integer(layers["l2"]["stride"], "L2 重叠", 0, layers["l2"]["max_tokens"] - 3)
    _integer(layers["l2"].get("batch_size"), "L2 批大小", 1, 64)
    _integer(layers["l3"].get("max_tokens"), "L3 上下文窗口", 256, 32768)
    _integer(layers["l3"].get("max_new_tokens"), "L3 最大生成 token", 8, 512)
    _number(layers["l5"]["similarity_threshold"], "泄露公共子串阈值", 10, 5000)
    for name, keys in {"l3": ["block_controversial"], "l4": ["spotlighting", "sandwich"], "l5": ["canary", "similarity", "guard_response"]}.items():
        for key in keys:
            if not isinstance(layers[name].get(key), bool):
                raise ValueError(f"{name}.{key} 必须是布尔值")
    fusion = config["fusion"]
    if fusion.get("strategy") not in ("any", "vote", "weighted"):
        raise ValueError("融合策略须为 any、vote 或 weighted")
    _number(fusion["threshold"], "融合阈值", 0, 1)
    for key in ("L1", "L2", "L3"):
        _number(fusion["weights"].get(key), f"{key} 权重", 0, 100)
    if sum(fusion["weights"].values()) <= 0:
        raise ValueError("至少一个检测层权重必须大于零")
    if not isinstance(fusion.get("fail_closed"), bool):
        raise ValueError("fail_closed 必须是布尔值")
    target = config["target"]
    if target.get("provider") not in ("ollama", "openai"):
        raise ValueError("目标模型提供方须为 ollama 或 openai")
    from urllib.parse import urlparse
    url = urlparse(target.get("base_url", ""))
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
        raise ValueError("模型地址必须是有效的 HTTP(S) URL，密钥请通过环境变量传入")
    _integer(target["max_tokens"], "最大生成 token", 1, 8192)
    _integer(target.get("context_length"), "目标模型上下文窗口", 512, 131072)
    for name in ("model", "small_model"):
        model = target.get(name)
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise ValueError(f"target.{name} 必须是非空字符串且不超过 200 字符")
    _number(target["timeout_seconds"], "模型超时", 1, 600)
    _number(target["temperature"], "生成温度", 0, 2)
    if not isinstance(target["system_prompt"], str) or len(target["system_prompt"]) > 8000:
        raise ValueError("系统提示词必须是字符串且不能超过 8000 字符")
    _integer(config["models"]["cpu_threads"], "CPU 线程数", 1, 256)
    for name in ("port", "frontend_port"):
        if name in config["app"]:
            _integer(config["app"][name], f"app.{name}", 1, 65535)
    origins = config.get("app", {}).get("cors_origins")
    if not isinstance(origins, list) or any(not isinstance(origin, str) for origin in origins):
        raise ValueError("app.cors_origins 必须是字符串列表")
    for key, high in {"max_detection_samples": 100000, "max_asr_samples": 1000, "max_queued_jobs": 4}.items():
        if key in config.get("evaluation", {}):
            _integer(config["evaluation"][key], key, 1, high)
    return config


def get_config() -> dict:
    with _lock:
        with CONFIG_PATH.open(encoding="utf-8") as stream:
            return copy.deepcopy(validate_config(yaml.safe_load(stream)))


def merge_dict(base: dict, updates: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_dict(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def save_config(updates: dict) -> dict:
    with _lock:
        result = validate_config(merge_dict(get_config(), updates))
        temporary = CONFIG_PATH.with_suffix(".yaml.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            yaml.safe_dump(result, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, CONFIG_PATH)
        return copy.deepcopy(result)


def public_config(config: dict | None = None) -> dict:
    config = copy.deepcopy(config or get_config())
    config.pop("auth", None)
    config.pop("database", None)
    return config
