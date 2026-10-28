"""A fresh checkout must contain the exact corpus needed to audit the thesis."""
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("kind,count", [("detect", 1116), ("asr", 200)])
def test_shipped_frozen_corpus_matches_original_experiment(kind, count):
    folder = ROOT / "data/frozen/thesis_v2_20261022"
    path = folder / f"{kind}_set.jsonl"
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((ROOT / "results/thesis_v2_20261022/summary.json").read_text(encoding="utf-8"))
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual_hash == manifest[f"{kind}_path_sha256"] == summary["dataset_hashes"][f"{kind}_path"]
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(records) == count
    assert len({row["id"] for row in records}) == count
