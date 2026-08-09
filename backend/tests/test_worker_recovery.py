"""Tests for worker recovery paths not covered by test_worker_evaluation.

Phase 7:  Worker document_missing failure when no proposal document exists.
Phase 12: CancelledError during evaluation must not leave proposal stuck.
"""

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import JSON, select
from sqlalchemy.dialects.postgresql import JSONB

os.environ["TESTING"] = "true"

from app.database import Base, async_session_factory, engine
from app.models.proposal import (
    FundingScheme,
    GuidelineVersion,
    ModelRun,
    ModelVersion,
    Proposal,
    ProposalDocument,
    ProposalVersion,
    RubricCriterion,
    RubricVersion,
    RuleDefinition,
)
from app.models.user import User, UserRole
from app.services.document_gate import GateResult
from app.services.model_registry import (
    CONTEXTUAL_BASELINE_NAME,
    CONTEXTUAL_BASELINE_VERSION,
    contextual_baseline_artifact_hash,
)


def _accepted_gate() -> GateResult:
    return GateResult(
        status="accepted", accepted=True, scoring_allowed=True,
        document_type="moc_st_proposal", declared_role="main_proposal",
        classified_role="main_proposal", role_status="confirmed",
        classification_reliability=0.8, word_count=300,
        structure_coverage=0.8, scheme_relevance=0.8,
        structure_signals=["objectives", "methodology", "work_plan", "budget", "team"],
        domain_signals=["coal_material", "mining_context", "sector_entities"],
        reasons=[],
    )


async def _seed():
    """Drop/recreate tables and seed a minimal graph. Returns lookup dict."""
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        scheme = FundingScheme(code="MOC-ST", name="Ministry of Coal S&T", is_active=True)
        session.add(scheme)
        await session.flush()

        gv = GuidelineVersion(
            scheme_id=scheme.id, version="1.0",
            effective_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            content={"rules": [], "rule_version": "1.0", "scheme_code": "MOC-ST",
                     "effective_date": "2024-01-01"},
        )
        session.add(gv)
        await session.flush()

        rv = RubricVersion(
            scheme_id=scheme.id, version="1",
            effective_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            total_marks=100, is_active=True,
        )
        session.add(rv)
        await session.flush()

        session.add(RubricCriterion(
            rubric_version_id=rv.id, criterion_key="project_duration",
            category="Project", criterion="Project Duration",
            maximum=20, weight=1.0, order=0,
        ))

        session.add(ModelVersion(
            id=CONTEXTUAL_BASELINE_NAME, model_name=CONTEXTUAL_BASELINE_NAME, version=CONTEXTUAL_BASELINE_VERSION,
            artifact_hash=contextual_baseline_artifact_hash(), rubric_version_id=rv.id,
            training_rows=0, test_metrics={}, is_active=True,
        ))

        session.add(RuleDefinition(
            rule_id="MOC-ST-001", guideline_version_id=gv.id,
            funding_scheme_id=scheme.id, category="eligibility",
            field="project_duration", operator="range", limit_value="12,36",
            severity="error", uncertainty_action="review",
            effective_date=datetime(2024, 1, 1, tzinfo=timezone.utc), is_active=True,
        ))

        session.add(User(
            id="worker-recovery-user", email="recovery@test.gov.in",
            role=UserRole.APPLICANT, is_active=True, is_verified=True,
        ))
        await session.commit()
        return {"scheme_id": scheme.id, "gv_id": gv.id, "rv_id": rv.id,
                "user_id": "worker-recovery-user"}


async def _add_proposal(base, with_doc=False):
    async with async_session_factory() as session:
        proposal = Proposal(
            owner_id=base["user_id"], scheme_id=base["scheme_id"],
            title="Recovery test", status="draft", current_version=1,
        )
        session.add(proposal)
        await session.flush()

        version = ProposalVersion(
            proposal_id=proposal.id, version_number=1,
            guideline_version_id=base["gv_id"],
            structured_data={"project_duration": "24"} if with_doc else {},
        )
        session.add(version)
        await session.flush()

        if with_doc:
            session.add(ProposalDocument(
                id=str(uuid.uuid4()),
                proposal_version_id=version.id,
                file_name="test.pdf", file_type="pdf", file_size=100,
                storage_path=f"proposals/{proposal.id}/test.pdf",
                sha256_hash="0" * 64,
                extracted_text="Coal project proposal with duration of 24 months.",
                extraction_version="1.0", ocr_used=False,
                upload_completed_at=datetime.now(timezone.utc),
            ))
        await session.commit()
        return proposal.id


# ============================================================
# PHASE 7 — WORKER DOCUMENT MISSING
# ============================================================


@pytest.mark.asyncio
async def test_worker_marks_failure_when_document_missing():
    """Worker must return document_missing error when no ProposalDocument exists."""
    base = await _seed()
    prop_id = await _add_proposal(base, with_doc=False)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("app.worker.evaluate_rules",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("N/A")))
    monkeypatch.setattr("app.worker.score_proposal",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("N/A")))

    from app.worker import evaluate_proposal

    result = await evaluate_proposal({}, prop_id, "MOC-ST", trigger_user_id=base["user_id"])
    assert result.get("error") == "document_missing"

    async with async_session_factory() as session:
        prop = (await session.execute(select(Proposal).where(Proposal.id == prop_id))).scalar_one()
        assert prop.status == "error"

        runs = (await session.execute(
            select(ModelRun).where(ModelRun.proposal_version_id == prop_id)
        )).scalars().all()
        for run in runs:
            assert run.status == "failed"
            assert run.failure_code == "document_missing"


# ============================================================
# PHASE 12 — WORKER CANCELLED ERROR
# ============================================================


@pytest.mark.asyncio
async def test_worker_cancelled_error_during_evaluation():
    """Cancellation is recorded so proposals cannot remain stuck in evaluating."""
    base = await _seed()
    prop_id = await _add_proposal(base, with_doc=True)

    async def cancel_in_rules(*args, **kwargs):
        raise __import__("asyncio").CancelledError("Worker cancelled")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("app.worker.assess_document", lambda *args, **kwargs: _accepted_gate())
    monkeypatch.setattr("app.worker.evaluate_rules", cancel_in_rules)
    monkeypatch.setattr(
        "app.worker.score_proposal",
        lambda *a, **kw: {
            "total_score": 0,
            "maximum_score": 100,
            "information_sufficiency": 0,
            "evidence_coverage": 0,
            "category_scores": [],
            "model_source": "contextual-rule-heuristic-v2",
            "abstention": True,
        },
    )

    from app.worker import evaluate_proposal

    with pytest.raises(__import__("asyncio").CancelledError):
        await evaluate_proposal(
            {}, prop_id, "MOC-ST", trigger_user_id=base["user_id"]
        )

    async with async_session_factory() as session:
        prop = (
            await session.execute(select(Proposal).where(Proposal.id == prop_id))
        ).scalar_one()
        assert prop.status == "error"
        run = (
            await session.execute(
                select(ModelRun)
                .join(ProposalVersion, ProposalVersion.id == ModelRun.proposal_version_id)
                .where(ProposalVersion.proposal_id == prop_id)
            )
        ).scalar_one()
        assert run.status == "failed"
        assert run.failure_code == "evaluation_cancelled"
