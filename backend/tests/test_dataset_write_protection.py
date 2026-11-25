import json
import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.app.core import config as settings_module
from backend.app.core.config import get_config
from backend.app.detectors.document_guard import RUNTIME_FILES
from scripts import build_dataset, download_document_guard, download_models, serve
from scripts.doctor import NodeTools


@pytest.fixture
def benign_rebuild_config(tmp_path, monkeypatch):
    config = get_config()
    config["data"].update(chinese_benign_count=0, encoded_count=0, indirect_count=0, asr_count=0)
    raw = tmp_path / "data/raw"
    raw.mkdir(parents=True)
    for name, content in (("deepset_test", "test input"), ("safety_prompts", "{}"), ("alpaca_zh", "[]")):
        (raw / build_dataset.SOURCES[name]["filename"]).write_text(content, encoding="utf-8")
    monkeypatch.setattr(pd, "read_parquet", lambda *args: pd.DataFrame([{"label": 0, "text": "Team meeting minutes"}]))
    return config


@pytest.mark.parametrize("absolute", [False, True])
def test_rebuild_rejects_frozen_output_before_touching_prepared_data(tmp_path, monkeypatch, absolute):
    prepared = tmp_path / "data/processed/detect_set.jsonl"
    prepared.parent.mkdir(parents=True)
    prepared.write_bytes(b"prepared data")
    frozen = Path("data/frozen/thesis/asr_set.jsonl")
    (tmp_path / frozen).parent.mkdir(parents=True)
    (tmp_path / frozen).write_bytes(b"saved result")
    config = get_config()
    config["data"]["asr_path"] = str(tmp_path / frozen if absolute else frozen)
    monkeypatch.setattr(build_dataset, "fetch_sources", lambda *args: pytest.fail("frozen target accessed source data"))

    with pytest.raises(ValueError, match="冻结语料目录禁止写入"):
        build_dataset.build_dataset(config, root=tmp_path)

    assert prepared.read_bytes() == b"prepared data"
    assert (tmp_path / frozen).read_bytes() == b"saved result"
    assert not (tmp_path / "data/raw").exists()


def test_rebuild_rejects_an_output_symbolic_link_to_frozen_data(tmp_path, monkeypatch):
    frozen = tmp_path / "data/frozen/thesis/manifest.json"
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(b"frozen manifest")
    manifest = tmp_path / "data/processed/manifest.json"
    manifest.parent.mkdir(parents=True)
    try:
        manifest.symlink_to(frozen)
    except OSError:
        pytest.skip("file symbolic links unavailable")
    monkeypatch.setattr(build_dataset, "fetch_sources", lambda *args: pytest.fail("frozen target accessed source data"))

    with pytest.raises(ValueError, match="冻结语料目录禁止写入"):
        build_dataset.build_dataset(get_config(), root=tmp_path)

    assert frozen.read_bytes() == b"frozen manifest"


@pytest.mark.parametrize("hard_link", [False, True])
def test_explicit_rebuild_updates_working_data_and_leaves_frozen_bytes_intact(tmp_path, benign_rebuild_config, hard_link):
    frozen = tmp_path / "data/frozen/thesis/detect_set.jsonl"
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(b"frozen source")
    prepared = tmp_path / benign_rebuild_config["data"]["detect_path"]
    prepared.parent.mkdir(parents=True)
    if hard_link:
        try:
            os.link(frozen, prepared)
        except OSError:
            pytest.skip("hard links unavailable")
    else:
        prepared.write_bytes(b"previous working data")

    manifest = build_dataset.build_dataset(benign_rebuild_config, offline=True, root=tmp_path)

    assert manifest["detect_count"] == 1
    assert manifest["detect_path_sha256"] == build_dataset.sha256(prepared)
    assert json.loads(prepared.read_text(encoding="utf-8"))["text"] == "Team meeting minutes"
    assert frozen.read_bytes() == b"frozen source"


@pytest.mark.parametrize("bad_destination,reason", [
    ("data/processed/output-directory", "目标必须是文件"),
    ("data/raw/sources.json", "不得覆盖原始数据"),
    ("data/raw/deepset-test.parquet", "不得覆盖原始数据"),
])
def test_rebuild_rejects_invalid_destination_before_fetching_sources(tmp_path, monkeypatch, bad_destination, reason):
    config = get_config()
    config["data"]["asr_path"] = bad_destination
    destination = tmp_path / bad_destination
    if bad_destination.endswith("output-directory"):
        destination.mkdir(parents=True)
    else:
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"original source material")
    monkeypatch.setattr(build_dataset, "fetch_sources", lambda *args: pytest.fail("invalid target accessed source data"))

    with pytest.raises(ValueError, match=reason):
        build_dataset.build_dataset(config, root=tmp_path)

    assert not (tmp_path / config["data"]["detect_path"]).exists()
    if destination.is_file():
        assert destination.read_bytes() == b"original source material"


@pytest.mark.parametrize("failed_file", ["asr_set.jsonl", "manifest.json"])
@pytest.mark.parametrize("existing_outputs", [False, True])
def test_failed_dataset_publication_restores_previous_output_set(tmp_path, monkeypatch, benign_rebuild_config, failed_file, existing_outputs):
    processed = tmp_path / "data/processed"
    processed.mkdir()
    previous = {processed / name: f"old {name}".encode() for name in ("detect_set.jsonl", "asr_set.jsonl", "manifest.json")}
    if existing_outputs:
        for path, content in previous.items():
            path.write_bytes(content)
    replace = Path.replace

    def fail_on_publication(source, destination):
        if source.name.startswith(".dataset-") and destination.name == failed_file:
            raise PermissionError("mock publication failure")
        return replace(source, destination)

    monkeypatch.setattr(Path, "replace", fail_on_publication)

    with pytest.raises(PermissionError, match="mock publication failure"):
        build_dataset.build_dataset(benign_rebuild_config, offline=True, root=tmp_path)

    assert {path: path.read_bytes() for path in processed.iterdir()} == (previous if existing_outputs else {})


def test_failed_restoration_reports_and_preserves_backup(tmp_path, monkeypatch, benign_rebuild_config):
    processed = tmp_path / "data/processed"
    processed.mkdir()
    detection = processed / "detect_set.jsonl"
    detection.write_bytes(b"previous detection")
    replace = Path.replace

    def fail_on_publication_and_restore(source, destination):
        if source.name.startswith(".dataset-") and destination.name == "asr_set.jsonl":
            raise PermissionError("mock publication failure")
        if source.name.startswith(".previous-") and destination == detection:
            raise PermissionError("mock rollback failure")
        return replace(source, destination)

    monkeypatch.setattr(Path, "replace", fail_on_publication_and_restore)

    with pytest.raises(RuntimeError, match="mock rollback failure") as error:
        build_dataset.build_dataset(benign_rebuild_config, offline=True, root=tmp_path)

    backup, = processed.glob(".previous-*")
    assert str(backup) in str(error.value)
    assert backup.read_bytes() == b"previous detection"


@pytest.mark.parametrize(("setup", "review_enabled", "review_present", "expect_download"), [
    (False, False, False, False),
    (False, True, True, False),
    (False, True, False, True),
    (True, True, True, True),
])
def test_startup_does_not_rebuild_missing_evaluation_data(tmp_path, monkeypatch, capsys, setup, review_enabled, review_present, expect_download):
    config = get_config()
    config["target"]["provider"] = "openai"
    config["documents"] = {"review_enabled": review_enabled}
    config["models"]["document_guard"] = {"path": "models/review-fixture"}
    review_dir = tmp_path / config["models"]["document_guard"]["path"]
    if review_present:
        for filename in RUNTIME_FILES:
            path = review_dir / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package-lock.json").write_bytes(b"test lock")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(serve, "ROOT", tmp_path)
    monkeypatch.setattr(settings_module, "resolve_path", lambda path: tmp_path / path)
    monkeypatch.setattr(settings_module, "get_config", lambda: config)
    monkeypatch.setattr(serve.bootstrap, "main", lambda: 0)
    monkeypatch.setattr(serve, "resolve_node_tools", lambda: NodeTools("node", "npm", "v22.12.0"))
    monkeypatch.setattr(serve, "healthy", lambda url: True)
    monkeypatch.setattr(serve, "project_api", lambda url: True)
    monkeypatch.setattr(serve.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(serve.signal, "signal", lambda *args: None)
    monkeypatch.setattr(serve, "threading", SimpleNamespace(Event=lambda: SimpleNamespace(wait=lambda seconds: True)))
    monkeypatch.setattr(download_models, "download", lambda key: None)
    monkeypatch.setattr(build_dataset, "build_dataset", lambda *args: pytest.fail("startup tried to rebuild evaluation data"))
    downloads = []

    def fail_download(path):
        downloads.append(path)
        raise OSError("optional model download unavailable")

    monkeypatch.setattr(download_document_guard, "download", fail_download)

    serve.run(setup=setup)

    output = capsys.readouterr().out
    assert "评测数据尚未准备" in output
    assert "Prompt Sentinel 已就绪" in output
    assert downloads == ([review_dir] if expect_download else [])
    assert ("复核不可用时保留原有文档拦截" in output) is expect_download
    assert not (tmp_path / "data").exists()
