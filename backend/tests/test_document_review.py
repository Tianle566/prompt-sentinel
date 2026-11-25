"""Document-only review preserves original evidence and fails closed."""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.app.api import routes
from backend.app.core.config import get_config, validate_config
from backend.app.db.models import RequestLog
from backend.app.schemas import DetectionResult, LayerResult, PipelineResult
from backend.app.services import document_review
from backend.tests.test_api import api


@pytest.fixture
def review_config():
    config = get_config()
    config["documents"] = {"review_enabled": True}
    config["fusion"].update(strategy="any", fail_closed=True)
    for name in ("l1", "l2", "l3", "l4", "l5"):
        config["layers"][name]["enabled"] = True
    config["layers"]["l4"].update(spotlighting=True, sandwich=True)
    config["layers"]["l5"].update(canary=True, similarity=True)
    return config


def detection(alarm=True):
    return DetectionResult(
        is_attack=alarm, reliable=True, fusion_score=float(alarm),
        layer_results=[
            LayerResult(layer="L1", is_attack=False, score=0),
            LayerResult(
                layer="L2", is_attack=alarm, score=0.98 if alarm else 0.02,
                categories=["prompt_injection"] if alarm else [],
                details={"window_scores": [0.98 if alarm else 0.02], "threshold": 0.5},
            ),
            LayerResult(layer="L3", is_attack=False, score=0, details={"safety": "Safe"}),
        ],
    )


@pytest.fixture
def review_input():
    texts = ["费用申请按规定的审批顺序办理。", "试用账号须在到期后关闭。", "档案由行政组统一保管。"]
    paragraphs = [
        {"index": i, "text": text, "is_attack": i < 2, "detection": detection(i < 2).model_dump(mode="json")}
        for i, text in enumerate(texts)
    ]
    flagged = [{"paragraph": i, "segment": 0, "text": text} for i, text in enumerate(texts[:2])]
    return "\n\n".join(texts), paragraphs, flagged


def guard_result(**changes):
    value = LayerResult(layer="L2_review", is_attack=False, score=0.02).model_dump(mode="json")
    value.update(changes)
    return SimpleNamespace(model_dump=lambda **kwargs: copy.deepcopy(value))


def test_review_requires_full_document_and_every_flagged_segment_before_changing_evidence(
    review_config, review_input, monkeypatch,
):
    text, paragraphs, flagged = review_input
    original = copy.deepcopy(paragraphs)
    calls = []

    def detect(content):
        assert paragraphs == original
        calls.append(content)
        return guard_result()

    monkeypatch.setattr(document_review, "DocumentGuard", lambda _: SimpleNamespace(detect=detect))
    trace = document_review.review_document(text, paragraphs, flagged, review_config)

    assert calls == [text, flagged[0]["text"], flagged[1]["text"]]
    assert trace["status"] == "allowed"
    assert [check["scope"] for check in trace["checks"]] == ["document", "segment", "segment"]
    assert paragraphs[2] == original[2]
    for updated, before in zip(paragraphs[:2], original[:2]):
        assert updated["is_attack"] is False
        assert updated["detection"]["is_attack"] is False
        assert updated["original_detection"] == before["detection"]
        raw = updated["original_detection"]["layer_results"][1]
        effective = updated["detection"]["layer_results"][1]
        assert raw["is_attack"] is True and raw["categories"] == ["prompt_injection"]
        assert effective["is_attack"] is False and effective["categories"] == []
        assert effective["score"] == raw["score"] == 0.98
        assert effective["details"]["original_is_attack"] is True
        assert effective["details"]["original_categories"] == raw["categories"]
        assert effective["details"]["window_scores"] == raw["details"]["window_scores"]
    paragraphs[0]["detection"]["layer_results"][1]["details"]["window_scores"].append(0.03)
    assert paragraphs[0]["original_detection"] == original[0]["detection"]


@pytest.mark.parametrize("failure,expected_status", [
    ({"is_attack": True, "score": 0.8}, "retained"),
    ({"is_attack": True, "score": 0.02}, "retained"),
    ({"is_attack": False, "score": 0.1}, "retained"),
    ({"status": "error", "score": None, "is_attack": None}, "error"),
    ({"status": "disabled"}, "error"),
    ({"enabled": False}, "error"),
    ({"score": float("nan")}, "error"),
    ({"score": float("inf")}, "error"),
    ({"score": -0.01}, "error"),
    ({"score": 1.01}, "error"),
    ({"score": False}, "error"),
    ({"score": "0.01"}, "error"),
    ({"is_attack": None}, "error"),
])
def test_later_segment_failure_preserves_all_original_decisions(
    review_config, review_input, monkeypatch, failure, expected_status,
):
    text, paragraphs, flagged = review_input
    original = copy.deepcopy(paragraphs)
    responses = iter([guard_result(), guard_result(), guard_result(**failure)])
    monkeypatch.setattr(document_review, "DocumentGuard", lambda _: SimpleNamespace(detect=lambda _: next(responses)))

    trace = document_review.review_document(text, paragraphs, flagged, review_config)

    assert trace["status"] == expected_status
    assert len(trace["checks"]) == 3
    assert paragraphs == original


def test_full_document_alarm_does_not_proceed_to_individual_segments(review_config, review_input, monkeypatch):
    text, paragraphs, flagged = review_input
    original = copy.deepcopy(paragraphs)
    calls = []

    def detect(content):
        calls.append(content)
        return guard_result(is_attack=True, score=0.9)

    monkeypatch.setattr(document_review, "DocumentGuard", lambda _: SimpleNamespace(detect=detect))
    trace = document_review.review_document(text, paragraphs, flagged, review_config)
    assert trace["status"] == "retained" and calls == [text]
    assert paragraphs == original


@pytest.mark.parametrize("failure_point", ["constructor", "later_segment", "evidence_copy"])
def test_unexpected_review_error_never_partially_rewrites_paragraphs(
    review_config, review_input, monkeypatch, failure_point,
):
    text, paragraphs, flagged = review_input
    if failure_point == "evidence_copy":
        del paragraphs[1]["detection"]["layer_results"][1]["details"]
    original = copy.deepcopy(paragraphs)
    calls = []

    def detect(content):
        calls.append(content)
        if failure_point == "later_segment" and len(calls) == 3:
            raise RuntimeError("synthetic inference failure")
        return guard_result()

    def construct(config):
        if failure_point == "constructor":
            raise RuntimeError("synthetic model initialization failure")
        return SimpleNamespace(detect=detect)

    monkeypatch.setattr(document_review, "DocumentGuard", construct)
    trace = document_review.review_document(text, paragraphs, flagged, review_config)
    assert trace["status"] == "error"
    assert paragraphs == original


@pytest.mark.parametrize("layer,state", [
    (layer, state)
    for layer in ("L1", "L3")
    for state in ("positive", "error", "disabled", "missing", "unknown")
])
def test_other_layer_alarm_or_incomplete_evidence_cannot_be_overridden(
    review_config, review_input, monkeypatch, layer, state,
):
    text, paragraphs, flagged = review_input
    rows = paragraphs[2]["detection"]["layer_results"]
    row = next(row for row in rows if row["layer"] == layer)
    if state == "positive":
        row["is_attack"] = True
    elif state == "error":
        row.update(status="error", is_attack=None, error="synthetic detector failure")
    elif state == "disabled":
        row.update(enabled=False, status="disabled", is_attack=None)
    elif state == "unknown":
        row["is_attack"] = None
    else:
        rows.remove(row)
    original = copy.deepcopy(paragraphs)
    monkeypatch.setattr(document_review, "DocumentGuard", lambda _: pytest.fail("unqualified review reached the model"))

    trace = document_review.review_document(text, paragraphs, flagged, review_config)

    assert trace["status"] == "skipped" and not trace["checks"]
    assert paragraphs == original


@pytest.mark.parametrize("path,value", [
    (("documents", "review_enabled"), False),
    (("fusion", "strategy"), "vote"),
    (("fusion", "strategy"), "weighted"),
    (("fusion", "fail_closed"), False),
    *[(("layers", layer, "enabled"), False) for layer in ("l1", "l2", "l3", "l4", "l5")],
    *[(("layers", "l4", feature), False) for feature in ("spotlighting", "sandwich")],
    *[(("layers", "l5", feature), False) for feature in ("canary", "similarity")],
])
def test_review_does_not_run_when_required_policy_is_disabled(
    review_config, review_input, monkeypatch, path, value,
):
    text, paragraphs, flagged = review_input
    section = review_config
    for key in path[:-1]:
        section = section[key]
    section[path[-1]] = value
    original = copy.deepcopy(paragraphs)
    monkeypatch.setattr(document_review, "DocumentGuard", lambda _: pytest.fail("ineligible policy reached the model"))

    trace = document_review.review_document(text, paragraphs, flagged, review_config)

    assert trace["status"] == "skipped" and not trace["checks"]
    assert paragraphs == original


@pytest.mark.parametrize("documents", [None, [], True, 1, "enabled", {"review_enabled": 1}, {"review_enabled": "false"}, {"review_enabled": None}])
def test_documents_configuration_rejects_invalid_types(documents):
    config = get_config()
    config["documents"] = documents
    with pytest.raises(ValueError, match="documents.review_enabled"):
        validate_config(config)


@pytest.mark.parametrize("documents", [{}, {"review_enabled": False}, {"review_enabled": True}])
def test_documents_configuration_accepts_only_boolean_review_flags(documents):
    config = get_config()
    config["documents"] = documents
    assert validate_config(config) == config
    config.pop("documents")
    assert validate_config(config) == config


@pytest.mark.parametrize("review_score", [0.02, 0.8])
def test_document_route_logs_one_result_with_review_and_original_evidence(
    api, review_config, monkeypatch, review_score,
):
    client, _, user, sessions = api
    monkeypatch.setattr(routes, "get_config", lambda: review_config)
    monkeypatch.setattr(routes, "_detection", lambda _: SimpleNamespace(detect=lambda text: detection("费用" in text)))
    monkeypatch.setattr(
        document_review, "DocumentGuard",
        lambda _: SimpleNamespace(detect=lambda text: guard_result(score=review_score, is_attack=review_score >= 0.1)),
    )
    generated = []

    def summarize(text, protected, *, detection, **kwargs):
        assert protected and detection.reliable and not detection.is_attack
        generated.append(text)
        return PipelineResult(output="费用申请依次审批，档案由行政组保管。", detection=detection, session_id="document-review-test").model_dump(mode="json")

    monkeypatch.setattr(routes, "_run", summarize)
    text = "费用申请按规定的审批顺序办理。\n\n档案由行政组统一保管。"
    response = client.post("/api/document/summarize", headers=user, files={"file": ("office.txt", text.encode(), "text/plain")})

    assert response.status_code == 200
    data = response.json()
    allowed = review_score < 0.1
    assert data["result"]["blocked"] is not allowed
    assert data["result"]["document_review"]["status"] == ("allowed" if allowed else "retained")
    assert generated == ([text] if allowed else [])
    with sessions() as db:
        rows = db.scalars(select(RequestLog)).all()
        assert len(rows) == 1 and rows[0].kind == "document"
        saved = rows[0].result
        assert saved["document_review"] == data["result"]["document_review"]
        assert saved["document"]["paragraphs"] == data["paragraphs"]
        first = saved["document"]["paragraphs"][0]
        original = first["original_detection"] if allowed else first["detection"]
        assert original["is_attack"] is True
        assert original["layer_results"][1]["score"] == 0.98
