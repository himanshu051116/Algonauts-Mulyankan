"""Worker evaluation persistence and failure handling tests."""

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import JSON, select
from sqlalchemy.dialects.postgresql import JSONB

os.environ["TESTING"] = "true"

from app.database import Base, async_session_factory, engine
from app.models.proposal import (
    AuditEvent,
    CriterionPrediction,
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
    RuleResult,
)
from app.models.user import User, UserRole
from app.services.document_gate import GateResult
from app.services.model_registry import (
    CONTEXTUAL_BASELINE_NAME,
    CONTEXTUAL_BASELINE_VERSION,
    contextual_baseline_artifact_hash,
)
from app.worker import evaluate_proposal




def _accepted_gate() -> GateResult:
    return GateResult(
        status="accepted",
        accepted=True,
        scoring_allowed=True,
        document_type="moc_st_proposal",
        declared_role="main_proposal",
        classified_role="main_proposal",
        role_status="confirmed",
        classification_reliability=0.8,
        word_count=500,
        structure_coverage=0.8,
        scheme_relevance=0.8,
        structure_signals=["objectives", "methodology", "work_plan", "budget", "team"],
        domain_signals=["coal_material", "mining_context", "sector_entities"],
        reasons=[],
    )

async def _seed_evaluation_graph():
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        scheme_result = await session.execute(
            select(FundingScheme).where(FundingScheme.code == "MOC-ST").limit(1)
        )
        scheme = scheme_result.scalar_one_or_none()
        if scheme is None:
            scheme = FundingScheme(code="MOC-ST", name="Ministry of Coal S&T", is_active=True)
            session.add(scheme)
            await session.flush()

        guideline_result = await session.execute(
            select(GuidelineVersion).where(GuidelineVersion.scheme_id == scheme.id).limit(1)
        )
        guideline = guideline_result.scalar_one_or_none()
        if guideline is None:
            guideline = GuidelineVersion(
                scheme_id=scheme.id,
                version="1.0",
                effective_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                content={"rules": []},
            )
            session.add(guideline)
            await session.flush()

        rubric_result = await session.execute(
            select(RubricVersion).where(RubricVersion.scheme_id == scheme.id).limit(1)
        )
        rubric = rubric_result.scalar_one_or_none()
        if rubric is None:
            rubric = RubricVersion(
                scheme_id=scheme.id,
                version="1.0",
                effective_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                total_marks=100,
                is_active=True,
            )
            session.add(rubric)
            await session.flush()

        criterion_result = await session.execute(
            select(RubricCriterion).where(
                RubricCriterion.rubric_version_id == rubric.id,
                RubricCriterion.criterion_key == "coal-specific-problem",
            ).limit(1)
        )
        criterion = criterion_result.scalar_one_or_none()
        if criterion is None:
            criterion = RubricCriterion(
                rubric_version_id=rubric.id,
                criterion_key="coal-specific-problem",
                category="Problem Definition, Need and Thrust Alignment",
                criterion="Problem is specific to coal/lignite operations",
                maximum=10,
                weight=1.0,
                description="Coal-specific problem",
                order=0,
            )
            session.add(criterion)
            await session.flush()

        model_result = await session.execute(
            select(ModelVersion).where(ModelVersion.model_name == CONTEXTUAL_BASELINE_NAME).limit(1)
        )
        model_version = model_result.scalar_one_or_none()
        if model_version is None:
            model_version = ModelVersion(
                id=CONTEXTUAL_BASELINE_NAME,
                model_name=CONTEXTUAL_BASELINE_NAME,
                version=CONTEXTUAL_BASELINE_VERSION,
                artifact_hash=contextual_baseline_artifact_hash(),
                rubric_version_id=rubric.id,
                training_rows=0,
                test_metrics={},
                is_active=True,
            )
            session.add(model_version)
        else:
            model_version.rubric_version_id = rubric.id

        user_result = await session.execute(
            select(User).where(User.email == "worker-test@example.com").limit(1)
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            user = User(
                id=str(uuid.uuid4()),
                email="worker-test@example.com",
                role=UserRole.APPLICANT,
                is_active=True,
                is_verified=True,
                full_name="Worker Test",
            )
            session.add(user)

        proposal = Proposal(
            id=str(uuid.uuid4()),
            owner_id=user.id,
            scheme_id=scheme.id,
            title="Worker evaluation test proposal",
            status="draft",
        )
        session.add(proposal)
        await session.flush()

        version = ProposalVersion(
            id=str(uuid.uuid4()),
            proposal_id=proposal.id,
            version_number=1,
            guideline_version_id=guideline.id,
            rubric_version_id=rubric.id,
            structured_data={"project_duration": "24"},
            package_status="confirmed",
            package_hash="b" * 64,
            package_policy_version="moc-st-package-v1",
            package_confirmed_at=datetime.now(timezone.utc),
            package_confirmed_by=user.id,
        )
        session.add(version)
        await session.flush()

        doc = ProposalDocument(
            id=str(uuid.uuid4()),
            proposal_version_id=version.id,
            file_name="proposal.pdf",
            file_type="pdf",
            file_size=1024,
            storage_path=f"proposals/{proposal.id}/proposal.pdf",
            sha256_hash="a" * 64,
            extracted_text="Coal mining safety research with clear coal and mine evidence.",
            extraction_version="1.0",
            ocr_used=False,
            upload_completed_at=datetime.now(timezone.utc),
        )
        session.add(doc)

        rule_definition = RuleDefinition(
            rule_id="rule-project-duration",
            guideline_version_id=guideline.id,
            funding_scheme_id=scheme.id,
            category="eligibility",
            field="project_duration",
            operator="required_field",
            limit_value=None,
            severity="error",
            uncertainty_action="review",
            source_reference="MOC-ST-1",
            effective_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            is_active=True,
        )
        rule_result = await session.execute(
            select(RuleDefinition).where(RuleDefinition.rule_id == "rule-project-duration").limit(1)
        )
        if rule_result.scalar_one_or_none() is None:
            session.add(rule_definition)
        await session.commit()

        return {
            "scheme": scheme,
            "user": user,
            "proposal": proposal,
            "version": version,
            "rubric": rubric,
            "criterion": criterion,
        }


@pytest.mark.asyncio
async def test_worker_evaluation_persists_full_run(monkeypatch):
    seed = await _seed_evaluation_graph()

    async def fake_rules(*args, **kwargs):
        return {
            "scheme_code": "MOC-ST",
            "rule_version": "1.0",
            "summary": {
                "eligible": False,
                "has_errors": False,
                "has_exceptions": False,
                "requires_human_review": True,
            },
            "results": [
                {
                    "rule_id": "rule-project-duration",
                    "category": "eligibility",
                    "field": "project_duration",
                    "result": "pass",
                    "evidence_coverage": 1.0,
                    "detail": "Duration provided",
                    "severity": "error",
                    "uncertainty_action": "review",
                    "source_reference": "MOC-ST-1",
                }
            ],
        }

    async def fake_scoring(*args, **kwargs):
        return {
            "scheme_code": "MOC-ST",
            "rubric_version": "1.0",
            "total_score": 71.0,
            "diagnostic_score": 71.0,
            "scoring_status": "released",
            "maximum_score": 100.0,
            "information_sufficiency": 0.88,
            "evidence_coverage": 0.88,
            "category_scores": [
                {
                    "category": "Problem Definition, Need and Thrust Alignment",
                    "maximum": 10,
                    "awarded": 7.0,
                    "released": True,
                    "criteria": [
                        {
                            "criterion_id": "coal-specific-problem",
                            "label": "Problem is specific to coal/lignite operations",
                            "awarded_score": 7.0,
                            "maximum_score": 10,
                            "ordinal_grade": 4,
                            "evidence_coverage": 0.9,
                            "information_sufficiency": 0.9,
                            "criterion_status": "supported",
                            "released": True,
                            "evidence_count": 1,
                            "evidence": [{"keyword": "coal", "text": "Coal mining safety problem", "count": 2, "document_role": "main_proposal", "verification_status": "contract_accepted"}],
                            "rationale": "Coal keyword evidence found",
                        }
                    ],
                }
            ],
            "model_source": "rubric-keyword",
            "abstention": False,
        }

    monkeypatch.setattr("app.worker.assess_document", lambda *args, **kwargs: _accepted_gate())
    monkeypatch.setattr("app.worker.evaluate_rules", fake_rules)
    monkeypatch.setattr("app.worker.score_proposal", fake_scoring)

    result = await evaluate_proposal({}, seed["proposal"].id, "MOC-ST", trigger_user_id=seed["user"].id)
    assert result["status"] == "completed"
    assert result["total_score"] == 71.0
    assert result["evaluation_payload"]["rule_evaluation"]["results"][0]["rule_id"] == "rule-project-duration"

    async with async_session_factory() as session:
        run_result = await session.execute(select(ModelRun).where(ModelRun.proposal_version_id == seed["version"].id))
        runs = run_result.scalars().all()
        assert len(runs) == 1
        run = runs[0]
        assert run.status == "completed"
        assert run.total_score == 71.0
        assert run.failure_code is None
        assert run.evaluation_payload["scoring"]["total_score"] == 71.0
        assert isinstance(
            run.evaluation_payload["submission_package"]["confirmed_at"], str
        )

        rule_result = await session.execute(select(RuleResult).where(RuleResult.model_run_id == run.id))
        rule_results = rule_result.scalars().all()
        assert len(rule_results) == 1
        assert rule_results[0].rule_identifier == "rule-project-duration"
        assert rule_results[0].result == "pass"

        criterion_result = await session.execute(
            select(CriterionPrediction).where(CriterionPrediction.model_run_id == run.id)
        )
        criterion_predictions = criterion_result.scalars().all()
        assert len(criterion_predictions) == 1
        assert criterion_predictions[0].awarded_score == 7.0

        proposal_result = await session.execute(select(Proposal).where(Proposal.id == seed["proposal"].id))
        proposal = proposal_result.scalar_one()
        assert proposal.status == "human_review"

    duplicate = await evaluate_proposal({}, seed["proposal"].id, "MOC-ST", trigger_user_id=seed["user"].id)
    assert duplicate["duplicate"] is True
    assert duplicate["model_run_id"] == result["model_run_id"]


@pytest.mark.asyncio
async def test_worker_evaluation_failure_marks_error(monkeypatch):
    seed = await _seed_evaluation_graph()

    async def fake_rules(*args, **kwargs):
        return {
            "scheme_code": "MOC-ST",
            "rule_version": "1.0",
            "summary": {
                "eligible": False,
                "has_errors": False,
                "has_exceptions": False,
                "requires_human_review": True,
            },
            "results": [],
        }

    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.worker.assess_document", lambda *args, **kwargs: _accepted_gate())
    monkeypatch.setattr("app.worker.evaluate_rules", fake_rules)
    monkeypatch.setattr("app.worker.score_proposal", boom)

    result = await evaluate_proposal({}, seed["proposal"].id, "MOC-ST", trigger_user_id=seed["user"].id)
    assert result["error"] == "evaluation_failed"

    async with async_session_factory() as session:
        run_result = await session.execute(select(ModelRun).where(ModelRun.proposal_version_id == seed["version"].id))
        run = run_result.scalar_one()
        assert run.status == "failed"
        assert run.failure_code == "evaluation_exception"
        assert run.error_message == "Evaluation failed"

        proposal_result = await session.execute(select(Proposal).where(Proposal.id == seed["proposal"].id))
        proposal = proposal_result.scalar_one()
        assert proposal.status == "error"

        audit_result = await session.execute(
            select(AuditEvent).where(AuditEvent.resource_id == seed["proposal"].id)
        )
        event_types = {event.event_type for event in audit_result.scalars().all()}
        assert "evaluation.failed" in event_types
        assert "proposal.status_transition" in event_types


@pytest.mark.asyncio
async def test_deterministic_evaluation_does_not_invoke_llm(monkeypatch):
    seed = await _seed_evaluation_graph()

    async def forbidden_llm(*args, **kwargs):
        raise AssertionError("LLM service must not be invoked by deterministic evaluation")

    async def fake_rules(*args, **kwargs):
        return {
            "scheme_code": "MOC-ST",
            "rule_version": "1.0",
            "summary": {"eligible": False, "requires_human_review": True},
            "results": [],
        }

    async def fake_scoring(*args, **kwargs):
        return {
            "scheme_code": "MOC-ST",
            "rubric_version": "1.0",
            "total_score": None,
            "diagnostic_score": 0.0,
            "scoring_status": "abstained",
            "maximum_score": 100.0,
            "information_sufficiency": 0.0,
            "evidence_coverage": 0.0,
            "category_scores": [],
            "model_source": "rubric-keyword",
            "abstention": True,
        }

    import app.services.llm as llm

    monkeypatch.setattr(llm, "_call_ollama", forbidden_llm)
    monkeypatch.setattr("app.worker.assess_document", lambda *args, **kwargs: _accepted_gate())
    monkeypatch.setattr("app.worker.evaluate_rules", fake_rules)
    monkeypatch.setattr("app.worker.score_proposal", fake_scoring)

    result = await evaluate_proposal({}, seed["proposal"].id, "MOC-ST", trigger_user_id=seed["user"].id)
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_worker_rejects_unsupported_scheme_before_evaluation(monkeypatch):
    seed = await _seed_evaluation_graph()

    async def forbidden(*args, **kwargs):
        raise AssertionError("Unsupported schemes must not enter evaluation")

    monkeypatch.setattr("app.worker.evaluate_rules", forbidden)
    monkeypatch.setattr("app.worker.score_proposal", forbidden)

    result = await evaluate_proposal({}, seed["proposal"].id, "CIL-RD", trigger_user_id=seed["user"].id)
    assert result["error"] == "unsupported_scheme"
