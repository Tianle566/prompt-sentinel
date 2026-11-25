"""Audit reports preserve prior experiment evidence and frozen source data."""
from __future__ import annotations

import json

import pytest

from scripts import audit_results


def test_audit_rejects_existing_report_before_reading_experiment(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_results, "ROOT", tmp_path)
    destination = tmp_path / "existing-evidence.json"
    destination.write_bytes(b"original evidence")

    with pytest.raises(FileExistsError):
        audit_results.audit("missing-experiment", report_path=destination)

    assert destination.read_bytes() == b"original evidence"


def test_audit_rejects_new_report_inside_frozen_data(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_results, "ROOT", tmp_path)
    destination = tmp_path / "data/frozen/original/new-report.json"

    with pytest.raises(ValueError, match="冻结"):
        audit_results.audit("missing-experiment", report_path=destination)

    assert not (tmp_path / "data").exists()


def test_repeated_default_audit_preserves_canonical_report(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_results, "ROOT", tmp_path)
    destination = tmp_path / "experiment/independent_audit.json"
    original = {"status": "passed", "checks_passed": 10}
    updated = {"status": "passed", "checks_passed": 12}

    first = audit_results._write_audit_report(destination, original, explicit=False)
    second = audit_results._write_audit_report(destination, updated, explicit=False)

    assert first == destination
    assert second != first and second.is_relative_to(tmp_path / "results")
    assert json.loads(first.read_text(encoding="utf-8")) == original
    assert json.loads(second.read_text(encoding="utf-8")) == updated


def test_concurrent_explicit_audit_cannot_replace_first_report(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_results, "ROOT", tmp_path)
    destination = audit_results._report_destination(tmp_path, "review.json")
    destination.write_bytes(b"first review")

    with pytest.raises(FileExistsError):
        audit_results._write_audit_report(destination, {"status": "passed"}, explicit=True)

    assert destination.read_bytes() == b"first review"
