"""Repeated acceptance runs must preserve prior reports before invoking models."""
import json

import pytest

from scripts.verification_output import prepare_report_path, write_report


def test_default_runs_never_replace_historical_report(tmp_path):
    historical = tmp_path / "results" / "smoke.json"
    historical.parent.mkdir()
    historical.write_bytes(b"original research evidence")
    first = prepare_report_path(tmp_path, None, "smoke", "smoke.json")
    second = prepare_report_path(tmp_path, None, "smoke", "smoke.json")
    write_report(first, {"run": 1})
    write_report(second, {"run": 2})
    assert first.parent != second.parent
    assert historical.read_bytes() == b"original research evidence"
    assert json.loads(first.read_text()) == {"run": 1}


def test_explicit_relative_directory_is_resolved_from_project(tmp_path):
    report = prepare_report_path(tmp_path, "results/new", "smoke", "smoke.json")
    assert report == tmp_path / "results/new/smoke.json"


def test_existing_report_is_rejected_before_work(tmp_path):
    prior = tmp_path / "smoke.json"
    prior.write_bytes(b"previous")
    with pytest.raises(FileExistsError, match="--output-dir"):
        prepare_report_path(tmp_path, tmp_path, "smoke", "smoke.json")
    assert prior.read_bytes() == b"previous"


def test_concurrent_writer_cannot_overwrite_report(tmp_path):
    path = prepare_report_path(tmp_path, tmp_path, "smoke", "smoke.json")
    write_report(path, {"winner": True})
    with pytest.raises(FileExistsError):
        write_report(path, {"winner": False})
    assert json.loads(path.read_text()) == {"winner": True}


def test_unserializable_report_does_not_create_partial_file(tmp_path):
    path = tmp_path / "report.json"
    with pytest.raises(TypeError):
        write_report(path, {"invalid": object()})
    assert not path.exists()


def test_smoke_stops_before_model_loading_for_existing_output(tmp_path, monkeypatch):
    from backend.app.services.detection import DetectionService
    from scripts import smoke_test

    (tmp_path / "smoke_cpu.json").write_text("prior")
    def unexpected(*args, **kwargs):
        pytest.fail("Model loading must not run when output would overwrite evidence")
    monkeypatch.setattr(DetectionService, "__init__", unexpected)
    with pytest.raises(FileExistsError):
        smoke_test.run("cpu", tmp_path)


def test_api_stops_before_credentials_or_http_for_existing_output(tmp_path, monkeypatch):
    from scripts import verify_system

    (tmp_path / "api_verification.json").write_text("prior")
    def unexpected(*args, **kwargs):
        pytest.fail("HTTP validation must not run when output would overwrite evidence")
    monkeypatch.setattr(verify_system.httpx, "Client", unexpected)
    with pytest.raises(FileExistsError):
        verify_system.verify(output_dir=tmp_path, credentials_file=tmp_path / "absent.json")
