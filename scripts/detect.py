#!/usr/bin/env python3
"""Display each detection layer for CLI text or stdin."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", nargs="?")
    parser.add_argument("--device", choices=["cpu", "auto", "cuda", "mps"])
    args = parser.parse_args()
    from backend.app.core.config import get_config
    from backend.app.services.detection import DetectionService
    config = get_config()
    if args.device:
        config["models"]["device"] = args.device
    text = args.text or sys.stdin.read()
    if not text.strip():
        parser.error("请提供文本或通过 stdin 输入")
    print(json.dumps(DetectionService(config).detect(text).model_dump(mode="json"), indent=2, ensure_ascii=False))
