from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.api import routes
from backend.app.core.config import get_config
from backend.app.db.models import Base, RequestLog, User
from backend.app.detectors.deberta import DebertaDetector
from backend.app.detectors.document_guard import REPO_ID, DocumentGuard
from backend.app.detectors.qwen_guard import QwenGuardDetector
from backend.app.llm.target import TargetLLM
from backend.app.schemas import LayerResult


@pytest.mark.parametrize("failure_stage", [None, "input", "merge", "signal"])
def test_document_trial_uses_only_horizon_and_logs_the_decision(monkeypatch, failure_stage):
    config = get_config()
    config["documents"] = {"review_enabled": True}
    config["layers"]["l5"]["guard_response"] = True
    config["fusion"].update(strategy="vote", fail_closed=False)
    config["target"]["context_length"] = 512
    text = ("季度会确定了仓库盘点的时间和参与人员。" * 10 + "\n\n") * 3
    summary = "会议确定了盘点安排。"
    calls = []
    generations = []

    def skip_other_model(*args, **kwargs):
        pytest.fail("Horizon 试用不应调用其他防护模型")

    def classify(self, value, *, threshold):
        assert threshold == 0.5
        calls.append(value)
        failure = failure_stage == ("merge" if value.startswith(summary) else "input")
        fields = {"layer": "L2_review", "details": {"repo": REPO_ID, "threshold": threshold}}
        if failure:
            return LayerResult(**fields, status="error", error="检测器不可用")
        if failure_stage == "signal":
            return LayerResult(**fields, score=0.8, is_attack=True, categories=["prompt_injection"])
        return LayerResult(**fields, score=0.2, is_attack=False)

    def generate(self, messages):
        generations.append(messages)
        return summary

    monkeypatch.setattr(routes, "get_config", lambda: config)
    monkeypatch.setattr(routes, "_detection", skip_other_model)
    monkeypatch.setattr(DebertaDetector, "detect", skip_other_model)
    monkeypatch.setattr(QwenGuardDetector, "detect", skip_other_model)
    monkeypatch.setattr(QwenGuardDetector, "moderate_response", skip_other_model)
    monkeypatch.setattr(DocumentGuard, "detect", classify)
    monkeypatch.setattr(TargetLLM, "generate", generate)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = User(username="trial-admin", role="admin", password_hash="unused")
        db.add(admin)
        db.commit()
        file = UploadFile(BytesIO(text.encode("utf-8")), filename="meeting.txt")
        response = routes.document(file=file, user=admin, db=db, detector_mode="horizon", protected="true")
        result = response["result"]
        log = db.scalars(select(RequestLog)).one()
        saved = log.result
        assert saved["document_detector"] == result["document_detector"] == "horizon"
        assert saved["document"]["paragraphs"] == response["paragraphs"]
        assert saved["detection"] == result["detection"]
        if failure_stage in {"input", "merge"}:
            assert log.attack_type == "unknown"
        elif failure_stage == "signal":
            assert log.attack_type == "indirect_injection"
    engine.dispose()

    assert "document_review" not in result
    assert [row["layer"] for row in result["detection"]["layer_results"]] == ["L1", "L2"]
    assert result["detection"]["layer_results"][1]["details"]["repo"] == REPO_ID
    assert config["layers"]["l5"]["guard_response"] is True
    assert config["fusion"]["strategy"] == "vote"
    if failure_stage in {"input", "merge"}:
        assert result["blocked"] and result["error"] and not result["detection"]["reliable"]
    if failure_stage == "signal":
        assert result["blocked"] and result["detection"]["reliable"] and result["error"] is None
    if failure_stage in {"input", "signal"}:
        assert not generations
    else:
        processing = result["document_processing"]
        assert processing["source_chunks"] > 1
        assert any(value.startswith(summary) for value in calls)
        assert processing["steps"][-1]["detection"]["layer_results"][1]["details"]["repo"] == REPO_ID
        if failure_stage == "merge":
            assert processing["steps"][-1]["detection"] == result["detection"]
        assert len(generations) == processing["source_chunks"] + int(failure_stage is None)
        if not failure_stage:
            assert not result["blocked"] and result["output"] == summary
            assert result["hardening"]["enabled"] and result["output_check"]["enabled"]
            assert result["output_check"]["details"]["guard_response"] is False


@pytest.mark.parametrize(("role", "protected", "status"), [("user", "true", 403), ("admin", "false", 422)])
def test_document_trial_requires_an_admin_and_active_protection(role, protected, status):
    user = User(username="trial-user", role=role, password_hash="unused")
    file = UploadFile(BytesIO(b"Meeting notes."), filename="meeting.txt")
    with pytest.raises(HTTPException) as error:
        routes.document(file=file, protected=protected, user=user, db=None, detector_mode="horizon")
    assert error.value.status_code == status
