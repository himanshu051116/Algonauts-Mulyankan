from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.user import User, UserRole
from app.models.proposal import RubricCriterion
from app.routers.reviews import _validate_shadow_annotations
from app.schemas.review import CriterionScoreRequest
from app.schemas.validation import (
    ValidationAssignmentCreateRequest,
    ValidationCaseExcludeRequest,
    ValidationStudyCreateRequest,
)
from app.services.access import (
    enforce_shadow_review_blindness,
    reviewer_model_output_is_blinded,
)
from app.services.validation import (
    ReviewObservation,
    consensus_from_reviews,
    pearson_correlation,
    recommendation_from_score,
    spearman_correlation,
)

ROOT = Path(__file__).resolve().parents[2]


def _review(total: float, recommendation: str, score: float) -> ReviewObservation:
    return ReviewObservation(
        review_id=f"review-{total}",
        assignment_id=f"assignment-{total}",
        total_score=total,
        recommendation=recommendation,
        criterion_scores={
            "criterion-1": {
                "score": score,
                "criterion_key": "technical-clarity",
                "criterion": "Technical clarity",
                "category": "Feasibility & Readiness",
                "maximum": 4.0,
            }
        },
    )


def test_consensus_requires_two_reviews():
    with pytest.raises(ValueError, match="At least two"):
        consensus_from_reviews([_review(60, "revision", 2.0)])


def test_consensus_computes_mean_and_reviewer_agreement():
    total, recommendation, criteria, agreement = consensus_from_reviews(
        [_review(60, "revision", 2.0), _review(70, "revision", 4.0)]
    )
    assert total == 65.0
    assert recommendation == "revision"
    assert criteria["criterion-1"]["score"] == 3.0
    assert criteria["criterion-1"]["reviewer_count"] == 2
    assert criteria["criterion-1"]["score_std"] == 1.0
    assert agreement["pairwise_total_mae"] == 10.0
    assert agreement["recommendation_agreement"] == 1.0


def test_consensus_does_not_invent_recommendation_on_tie():
    _, recommendation, _, agreement = consensus_from_reviews(
        [_review(59, "rejected", 2.0), _review(61, "revision", 2.5)]
    )
    assert recommendation is None
    assert agreement["recommendation_agreement"] == 0.5


def test_correlations_are_correct_for_monotonic_examples():
    assert pearson_correlation([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert spearman_correlation([10, 20, 30], [3, 2, 1]) == pytest.approx(-1.0)


def test_correlations_abstain_on_invalid_or_constant_input():
    assert pearson_correlation([1], [1]) is None
    assert pearson_correlation([1, 1], [2, 3]) is None
    assert spearman_correlation([1, 2], [1]) is None


def test_recommendation_policy_is_explicit_and_bounded():
    policy = {"approved_min": 80, "revision_min": 60}
    assert recommendation_from_score(80, policy) == "approved"
    assert recommendation_from_score(60, policy) == "revision"
    assert recommendation_from_score(59.9, policy) == "rejected"
    assert recommendation_from_score(70, {}) is None
    assert recommendation_from_score(70, {"approved_min": 50, "revision_min": 60}) is None


def test_study_request_defaults_to_shadow_and_two_reviews():
    request = ValidationStudyCreateRequest(name="Expert validation pilot")
    assert request.scheme_code == "MOC-ST"
    assert request.shadow_mode is True
    assert request.minimum_reviews_per_case == 2
    assert request.protocol_version == "expert-grounded-validation-v1"
    assert request.annotation_rulebook_version == "expert-annotation-rulebook-v1"


def test_study_request_rejects_single_reviewer_design():
    with pytest.raises(ValidationError):
        ValidationStudyCreateRequest(
            name="Invalid pilot", minimum_reviews_per_case=1
        )


def test_assignment_request_normalizes_email():
    request = ValidationAssignmentCreateRequest(
        reviewer_email="  Reviewer@Example.COM  "
    )
    assert request.reviewer_email == "reviewer@example.com"


class _Result:
    def __init__(self, value: str | None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Db:
    def __init__(self, value: str | None):
        self.value = value
        self.executed = False

    async def execute(self, _statement):
        self.executed = True
        return _Result(self.value)


@pytest.mark.asyncio
async def test_non_reviewer_is_never_shadow_blinded():
    db = _Db("assignment")
    user = User(id="admin", email="admin@example.com", role=UserRole.ADMINISTRATOR)
    assert await reviewer_model_output_is_blinded(db, user, "proposal") is False
    assert db.executed is False


@pytest.mark.asyncio
async def test_active_blind_assignment_hides_model_output():
    db = _Db("assignment")
    user = User(
        id="reviewer",
        email="reviewer@example.com",
        role=UserRole.TECHNICAL_REVIEWER,
    )
    assert await reviewer_model_output_is_blinded(db, user, "proposal") is True
    assert db.executed is True


def test_validation_migration_is_additive_and_at_chain_head():
    migration = (ROOT / "migrations/versions/20260709_validation_pilot.py").read_text()
    assert 'revision: str = "20260709_validation_pilot"' in migration
    assert 'down_revision: str | None = "20260708_packages"' in migration
    for table in (
        "validation_studies",
        "validation_cases",
        "validation_consensus",
        "shadow_comparisons",
        "validation_metric_snapshots",
    ):
        assert f'op.create_table(\n        "{table}"' in migration
    assert 'op.add_column(\n        "reviewer_assignments"' in migration
    assert 'op.add_column(\n        "expert_reviews"' in migration
    assert "op.drop_table(\"proposals\")" not in migration
    assert "op.drop_table(\"model_runs\")" not in migration


def test_protocol_and_rulebook_are_source_controlled():
    protocol = ROOT / "data/validation/expert-grounded-validation-protocol-v1.yaml"
    rulebook = ROOT / "data/validation/expert-annotation-rulebook-v1.yaml"
    assert protocol.exists()
    assert rulebook.exists()
    assert "model_output_hidden_until_review_submission: true" in protocol.read_text()
    assert "minimum_independent_reviews_per_case: 2" in protocol.read_text()
    assert "Do not access model scores" in rulebook.read_text()


def test_validation_router_is_registered_and_version_is_updated():
    main = (ROOT / "backend/app/main.py").read_text()
    health = (ROOT / "backend/app/routers/health.py").read_text()
    package = (ROOT / "package.json").read_text()
    assert "validation.router" in main
    assert 'prefix="/api/v1/validation"' in main
    assert 'version="0.8.0"' in main
    assert '"version": "0.8.0"' in health
    assert '"version": "0.8.0"' in package


def test_windows_upgrade_script_preserves_data_and_verifies_live_schema():
    script = (
        ROOT / "scripts/windows/upgrade-expert-validation-0.8.0.ps1"
    ).read_text()
    assert "postgres-before-0.8.0.sql" in script
    assert "Get-CoreRecordCounts" in script
    assert "verify_validation_pilot" in script
    assert "verify_model_registry" in script
    assert 'health.version -eq "0.8.0"' in script
    assert "docker compose down -v" not in script
    assert "docker volume rm" not in script
    assert "Existing proposals, documents, evaluations, reviews and model runs were preserved" in script


def test_shadow_annotations_require_rationale_and_page_provenance():
    criterion = RubricCriterion(
        id="criterion-1",
        criterion_key="technical-clarity",
        criterion="Technical clarity",
        category="Feasibility",
        maximum=4,
        order=1,
    )
    incomplete = CriterionScoreRequest(
        criterion_id=criterion.id, score=2, rationale=None, page_references=[]
    )
    with pytest.raises(Exception) as exc:
        _validate_shadow_annotations({criterion.id: (criterion, incomplete)})
    assert getattr(exc.value, "status_code", None) == 422
    assert exc.value.detail["code"] == "incomplete_shadow_annotation"


def test_shadow_annotations_accept_traceable_criterion_label():
    criterion = RubricCriterion(
        id="criterion-1",
        criterion_key="technical-clarity",
        criterion="Technical clarity",
        category="Feasibility",
        maximum=4,
        order=1,
    )
    complete = CriterionScoreRequest(
        criterion_id=criterion.id,
        score=2,
        rationale="The methodology is partially specified on the cited page.",
        page_references=[7],
    )
    _validate_shadow_annotations({criterion.id: (criterion, complete)})


def test_study_freezes_model_artifact_and_rubric_definition_hashes():
    model = (ROOT / "backend/app/models/proposal.py").read_text()
    migration = (ROOT / "migrations/versions/20260709_validation_pilot.py").read_text()
    router = (ROOT / "backend/app/routers/validation.py").read_text()
    service = (ROOT / "backend/app/services/validation.py").read_text()
    for field in ("model_artifact_hash", "rubric_definition_hash"):
        assert field in model
        assert field in migration
        assert field in router
        assert field in service
    assert '"frozen": {"completed", "archived"}' in router
    assert '"frozen": {"completed", "active", "archived"}' not in router


def test_release_packager_excludes_runtime_upgrade_backups():
    packager = (ROOT / "scripts/quality/create-release.py").read_text()
    assert '"backups"' in packager


def test_upgrade_script_counts_real_core_tables():
    script = (
        ROOT / "scripts/windows/upgrade-expert-validation-0.8.0.ps1"
    ).read_text()
    assert "FROM proposal_documents" in script
    assert "FROM documents" not in script


def test_consensus_flags_material_expert_disagreement():
    _, _, _, agreement = consensus_from_reviews(
        [_review(45, "rejected", 1.0), _review(70, "revision", 4.0)]
    )
    assert agreement["total_score_range"] == 25.0
    assert agreement["recommendation_disagreement"] is True
    assert agreement["material_disagreement"] is True
    assert agreement["adjudication_recommended"] is True


def test_consensus_does_not_flag_close_agreeing_reviews():
    _, _, _, agreement = consensus_from_reviews(
        [_review(61, "revision", 2.0), _review(68, "revision", 3.0)]
    )
    assert agreement["total_score_range"] == 7.0
    assert agreement["material_disagreement"] is False


def test_case_exclusion_requires_a_traceable_reason():
    with pytest.raises(ValidationError):
        ValidationCaseExcludeRequest(reason="short")
    assert (
        ValidationCaseExcludeRequest(reason="  Duplicate proposal family detected.  ").reason
        == "Duplicate proposal family detected."
    )


@pytest.mark.asyncio
async def test_blindness_guard_blocks_sensitive_shadow_information():
    db = _Db("assignment")
    user = User(
        id="reviewer",
        email="reviewer@example.com",
        role=UserRole.TECHNICAL_REVIEWER,
    )
    with pytest.raises(Exception) as exc:
        await enforce_shadow_review_blindness(db, user, "proposal")
    assert getattr(exc.value, "status_code", None) == 403
    assert exc.value.detail["code"] == "shadow_review_blinded"


def test_blindness_boundary_covers_outcome_and_machine_derived_routes():
    proposals = (ROOT / "backend/app/routers/proposals.py").read_text()
    governance = (ROOT / "backend/app/routers/governance.py").read_text()
    storage = (ROOT / "backend/app/routers/storage.py").read_text()
    reviews = (ROOT / "backend/app/routers/reviews.py").read_text()
    assert 'status_override=(\n            "shadow_review"' in proposals
    assert governance.count("enforce_shadow_review_blindness(") >= 3
    assert "Machine-extracted fields are hidden" in storage
    assert "reviewer_model_output_is_blinded" in reviews


def test_case_exclusion_is_audited_and_freeze_safe():
    router = (ROOT / "backend/app/routers/validation.py").read_text()
    frontend = (ROOT / "src/api/validation.ts").read_text()
    assert '@router.patch("/cases/{case_id}/exclude"' in router
    assert 'study.status not in {"draft", "active"}' in router
    assert 'event_type="validation.case_excluded"' in router
    assert "excludeValidationCase" in frontend


def test_protocol_blinding_and_adjudication_language_matches_implementation():
    protocol = (
        ROOT / "data/validation/expert-grounded-validation-protocol-v1.yaml"
    ).read_text()
    rulebook = (
        ROOT / "data/validation/expert-annotation-rulebook-v1.yaml"
    ).read_text()
    assert "machine_extracted_fields_hidden_until_review_submission: true" in protocol
    assert "proposal_outcome_and_adjudication_hidden_until_review_submission: true" in protocol
    assert "material_disagreement_flagged_for_adjudication: true" in protocol
    assert "recommended_for_material_disagreement: true" in rulebook
    assert "required_for_observational_metrics: false" in rulebook
