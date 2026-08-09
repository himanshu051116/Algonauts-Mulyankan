from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.database import get_db
from app.domain import AssignmentRole, AssignmentStatus, ProposalStatus
from app.models.proposal import (
    ExpertCriterionScore,
    ExpertReview,
    ModelMonitoringMetric,
    ModelRun,
    ModelVersion,
    Proposal,
    ProposalVersion,
    ReviewerAssignment,
    RubricCriterion,
    RubricVersion,
    ValidationCase,
    ValidationStudy,
)
from app.models.user import User, UserRole
from app.schemas.review import (
    AssignmentListResponse,
    CriterionScoreRequest,
    CriterionScoreResponse,
    ExpertReviewResponse,
    ProposalReviewsResponse,
    ReviewAssignRequest,
    ReviewAssignResponse,
    ReviewerAssignmentResponse,
    ReviewSubmitRequest,
    ReviewSubmitResponse,
)
from app.services.access import (
    get_proposal_for_user,
    reviewer_model_output_is_blinded,
)
from app.services.audit import create_audit_event

router = APIRouter()

COORDINATOR_ROLES = {
    UserRole.ADMINISTRATOR,
    UserRole.SCRUTINY_OFFICER,
    UserRole.COMMITTEE_SECRETARIAT,
    UserRole.SENIOR_ADJUDICATOR,
    UserRole.AUDITOR,
}


class ConflictDeclareRequest(BaseModel):
    notes: str = Field(min_length=3, max_length=5000)


class ConflictResolutionRequest(BaseModel):
    resolution: str = Field(pattern="^(cleared|cancelled)$")
    notes: str = Field(min_length=3, max_length=5000)


async def _resolve_rubric_criterion_id(db: AsyncSession, criterion_id: str) -> str:
    """Resolve a criterion database id or stable criterion key.

    Retained as a small reusable validator for API compatibility and tests.
    Submission handling performs the stricter active-rubric membership check.
    """
    cleaned = criterion_id.strip()
    if not cleaned:
        raise HTTPException(
            status_code=400, detail="Criterion score is missing criterion_id"
        )
    result = await db.execute(
        select(RubricCriterion)
        .where(
            or_(RubricCriterion.id == cleaned, RubricCriterion.criterion_key == cleaned)
        )
        .limit(1)
    )
    criterion = result.scalar_one_or_none()
    if criterion is None:
        raise HTTPException(
            status_code=400, detail=f"Unknown rubric criterion '{cleaned}'"
        )
    return criterion.id


def _assignment_response(
    assignment: ReviewerAssignment,
    proposal_version_number: int,
) -> ReviewerAssignmentResponse:
    return ReviewerAssignmentResponse(
        id=assignment.id,
        proposal_id=assignment.proposal_id,
        proposal_version_id=assignment.proposal_version_id,
        proposal_version_number=proposal_version_number,
        reviewer_id=assignment.reviewer_id,
        validation_case_id=assignment.validation_case_id,
        is_shadow_validation=assignment.validation_case_id is not None,
        validation_study_name=None,
        role=assignment.role,
        status=assignment.status,
        is_blind=assignment.is_blind,
        conflict_declared=assignment.conflict_declared,
        conflict_notes=assignment.conflict_notes,
        assigned_at=assignment.assigned_at,
        completed_at=assignment.completed_at,
    )


async def _active_rubric_for_assignment(
    db: AsyncSession,
    assignment: ReviewerAssignment,
) -> RubricVersion:
    version_result = await db.execute(
        select(ProposalVersion).where(
            ProposalVersion.id == assignment.proposal_version_id,
            ProposalVersion.proposal_id == assignment.proposal_id,
        )
    )
    version = version_result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=409, detail="Proposal version is missing")

    if version.rubric_version_id:
        rubric_result = await db.execute(
            select(RubricVersion).where(RubricVersion.id == version.rubric_version_id)
        )
        rubric = rubric_result.scalar_one_or_none()
        if rubric:
            return rubric

    run_result = await db.execute(
        select(RubricVersion)
        .join(ModelVersion, ModelVersion.rubric_version_id == RubricVersion.id)
        .join(ModelRun, ModelRun.model_version_id == ModelVersion.id)
        .where(ModelRun.proposal_version_id == version.id)
        .order_by(ModelRun.created_at.desc())
        .limit(1)
    )
    rubric = run_result.scalar_one_or_none()
    if rubric:
        return rubric

    proposal_result = await db.execute(
        select(Proposal).where(Proposal.id == assignment.proposal_id)
    )
    proposal = proposal_result.scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    active_result = await db.execute(
        select(RubricVersion)
        .where(
            RubricVersion.scheme_id == proposal.scheme_id,
            RubricVersion.is_active.is_(True),
        )
        .order_by(RubricVersion.effective_date.desc())
        .limit(1)
    )
    rubric = active_result.scalar_one_or_none()
    if rubric is None:
        raise HTTPException(status_code=409, detail="No active rubric is configured")
    return rubric


def _validate_shadow_annotations(
    submitted: dict[str, tuple[RubricCriterion, CriterionScoreRequest]],
) -> None:
    """Require traceable criterion annotations for expert-validation labels."""

    missing_rationale: list[str] = []
    missing_pages: list[str] = []
    for criterion, item in submitted.values():
        label = criterion.criterion_key or criterion.id
        if not item.rationale or len(item.rationale.strip()) < 10:
            missing_rationale.append(label)
        if not item.page_references:
            missing_pages.append(label)
    if missing_rationale or missing_pages:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "incomplete_shadow_annotation",
                "missing_rationale": missing_rationale,
                "missing_page_references": missing_pages,
                "message": (
                    "Every shadow-pilot criterion requires a concise rationale and "
                    "at least one proposal or supporting-document page reference."
                ),
            },
        )


async def _record_review_monitoring(
    db: AsyncSession,
    assignment: ReviewerAssignment,
    expert_score: float,
    recommendation: str,
) -> None:
    """Persist model-versus-review deltas for later validation and drift analysis.

    These metrics are observational. They never alter the proposal decision or
    imply that the bootstrap model is calibrated.
    """

    result = await db.execute(
        select(ModelRun)
        .where(
            ModelRun.proposal_version_id == assignment.proposal_version_id,
            ModelRun.status == "completed",
        )
        .order_by(ModelRun.completed_at.desc(), ModelRun.created_at.desc())
        .limit(1)
    )
    model_run = result.scalar_one_or_none()
    if model_run is None:
        return

    suffix = assignment.id
    if model_run.total_score is not None:
        delta = float(expert_score) - float(model_run.total_score)
        db.add(
            ModelMonitoringMetric(
                model_run_id=model_run.id,
                metric_name=f"expert_score_delta:{suffix}",
                metric_value=delta,
            )
        )
        db.add(
            ModelMonitoringMetric(
                model_run_id=model_run.id,
                metric_name=f"expert_abs_error:{suffix}",
                metric_value=abs(delta),
            )
        )
        expected = (
            "approved"
            if model_run.total_score >= 80
            else "revision"
            if model_run.total_score >= 60
            else "rejected"
        )
        db.add(
            ModelMonitoringMetric(
                model_run_id=model_run.id,
                metric_name=f"expert_recommendation_disagreement:{suffix}",
                metric_value=0.0 if expected == recommendation else 1.0,
            )
        )
    if model_run.abstention_reason:
        db.add(
            ModelMonitoringMetric(
                model_run_id=model_run.id,
                metric_name=f"expert_review_after_abstention:{suffix}",
                metric_value=1.0,
            )
        )


@router.get("/assignments", response_model=AssignmentListResponse)
async def list_assignments(
    proposal_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(ReviewerAssignment, ProposalVersion.version_number).join(
        ProposalVersion,
        ProposalVersion.id == ReviewerAssignment.proposal_version_id,
    )
    if current_user.role not in COORDINATOR_ROLES:
        query = query.where(ReviewerAssignment.reviewer_id == current_user.id)
    if proposal_id:
        await get_proposal_for_user(
            db, current_user, proposal_id, conceal_existence=True
        )
        query = query.where(ReviewerAssignment.proposal_id == proposal_id)
    result = await db.execute(query.order_by(ReviewerAssignment.assigned_at.desc()))
    return AssignmentListResponse(
        assignments=[
            _assignment_response(assignment, version_number)
            for assignment, version_number in result.all()
        ]
    )


@router.post("/assignments", response_model=ReviewAssignResponse)
async def assign_reviewer(
    body: ReviewAssignRequest,
    request: Request,
    current_user: User = Depends(
        require_role(
            UserRole.ADMINISTRATOR,
            UserRole.SCRUTINY_OFFICER,
            UserRole.COMMITTEE_SECRETARIAT,
        )
    ),
    db: AsyncSession = Depends(get_db),
):
    proposal_result = await db.execute(
        select(Proposal).where(Proposal.id == body.proposal_id)
    )
    proposal = proposal_result.scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status not in {
        ProposalStatus.HUMAN_REVIEW.value,
        ProposalStatus.ADJUDICATION.value,
    }:
        raise HTTPException(
            status_code=409,
            detail="Reviewers can only be assigned after automated scrutiny",
        )

    version_result = await db.execute(
        select(ProposalVersion).where(
            ProposalVersion.proposal_id == proposal.id,
            ProposalVersion.version_number == proposal.current_version,
        )
    )
    proposal_version = version_result.scalar_one_or_none()
    if proposal_version is None:
        raise HTTPException(
            status_code=409, detail="Current proposal version is missing"
        )

    reviewer_result = await db.execute(
        select(User).where(User.email == body.reviewer_email)
    )
    reviewer = reviewer_result.scalar_one_or_none()
    if reviewer is None:
        raise HTTPException(status_code=404, detail="Reviewer not found")
    if reviewer.id == proposal.owner_id:
        raise HTTPException(
            status_code=400, detail="Proposal owners cannot review their own proposals"
        )
    if not reviewer.is_active or not reviewer.is_verified:
        raise HTTPException(
            status_code=400, detail="Reviewer account is not active and verified"
        )

    expected_role = (
        UserRole.TECHNICAL_REVIEWER
        if body.role == AssignmentRole.TECHNICAL
        else UserRole.FINANCIAL_REVIEWER
    )
    if reviewer.role != expected_role:
        raise HTTPException(
            status_code=400,
            detail=f"The selected user must have role '{expected_role.value}'",
        )

    existing_result = await db.execute(
        select(ReviewerAssignment).where(
            ReviewerAssignment.proposal_version_id == proposal_version.id,
            ReviewerAssignment.reviewer_id == reviewer.id,
        )
    )
    assignment = existing_result.scalar_one_or_none()
    created = assignment is None
    if assignment is None:
        assignment = ReviewerAssignment(
            proposal_id=body.proposal_id,
            proposal_version_id=proposal_version.id,
            reviewer_id=reviewer.id,
            assigned_by=current_user.id,
            role=body.role.value,
            status=AssignmentStatus.PENDING.value,
            is_blind=True,
        )
        db.add(assignment)
        await db.flush()
    elif assignment.status == AssignmentStatus.COMPLETED.value:
        raise HTTPException(
            status_code=409, detail="The reviewer has already completed this assignment"
        )
    else:
        assignment.role = body.role.value
        assignment.assigned_by = current_user.id
        assignment.status = AssignmentStatus.PENDING.value
        assignment.conflict_declared = None
        assignment.conflict_notes = None

    await create_audit_event(
        db,
        event_type="reviewer.assigned" if created else "reviewer.reassigned",
        user=current_user,
        resource_type="reviewer_assignment",
        resource_id=assignment.id,
        details={
            "proposal_id": body.proposal_id,
            "proposal_version_id": proposal_version.id,
            "proposal_version_number": proposal_version.version_number,
            "reviewer_id": reviewer.id,
            "role": assignment.role,
            "created": created,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    await db.refresh(assignment)
    return ReviewAssignResponse(
        assignment=_assignment_response(assignment, proposal_version.version_number),
        status="created" if created else "updated",
        message="Reviewer assigned." if created else "Reviewer assignment updated.",
    )


@router.post("/{assignment_id}/conflict")
async def declare_conflict(
    assignment_id: str,
    body: ConflictDeclareRequest,
    request: Request,
    current_user: User = Depends(
        require_role(UserRole.TECHNICAL_REVIEWER, UserRole.FINANCIAL_REVIEWER)
    ),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ReviewerAssignment).where(
            ReviewerAssignment.id == assignment_id,
            ReviewerAssignment.reviewer_id == current_user.id,
        )
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if assignment.status == AssignmentStatus.COMPLETED.value:
        raise HTTPException(
            status_code=409,
            detail="Completed assignments cannot declare a new conflict",
        )

    assignment.conflict_declared = True
    assignment.conflict_notes = body.notes.strip()
    assignment.status = AssignmentStatus.CONFLICT_DECLARED.value
    await create_audit_event(
        db,
        event_type="conflict.declared",
        user=current_user,
        resource_type="reviewer_assignment",
        resource_id=assignment_id,
        details={"proposal_id": assignment.proposal_id, "notes": body.notes.strip()},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return {
        "assignment_id": assignment_id,
        "status": AssignmentStatus.CONFLICT_DECLARED.value,
    }


@router.post("/{assignment_id}/conflict/resolve")
async def resolve_conflict(
    assignment_id: str,
    body: ConflictResolutionRequest,
    request: Request,
    current_user: User = Depends(
        require_role(
            UserRole.ADMINISTRATOR,
            UserRole.SCRUTINY_OFFICER,
            UserRole.COMMITTEE_SECRETARIAT,
        )
    ),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ReviewerAssignment).where(ReviewerAssignment.id == assignment_id)
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if assignment.conflict_declared is not True:
        raise HTTPException(
            status_code=409, detail="No declared conflict is awaiting resolution"
        )

    assignment.conflict_declared = False if body.resolution == "cleared" else True
    assignment.conflict_notes = (
        f"{assignment.conflict_notes or ''}\nResolution: {body.notes}".strip()
    )
    assignment.status = (
        AssignmentStatus.PENDING.value
        if body.resolution == "cleared"
        else AssignmentStatus.CANCELLED.value
    )
    await create_audit_event(
        db,
        event_type="conflict.resolved",
        user=current_user,
        resource_type="reviewer_assignment",
        resource_id=assignment_id,
        details={"resolution": body.resolution, "notes": body.notes},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return {"assignment_id": assignment_id, "status": assignment.status}


@router.post("/{assignment_id}/submit", response_model=ReviewSubmitResponse)
async def submit_review(
    assignment_id: str,
    body: ReviewSubmitRequest,
    request: Request,
    current_user: User = Depends(
        require_role(UserRole.TECHNICAL_REVIEWER, UserRole.FINANCIAL_REVIEWER)
    ),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ReviewerAssignment).where(
            ReviewerAssignment.id == assignment_id,
            ReviewerAssignment.reviewer_id == current_user.id,
        )
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if assignment.status in {
        AssignmentStatus.COMPLETED.value,
        AssignmentStatus.CANCELLED.value,
    }:
        raise HTTPException(
            status_code=409, detail="Review cannot be submitted for this assignment"
        )
    if assignment.conflict_declared is True:
        raise HTTPException(
            status_code=409,
            detail="Resolve the declared conflict before submitting a review",
        )

    proposal_result = await db.execute(
        select(Proposal).where(Proposal.id == assignment.proposal_id)
    )
    proposal = proposal_result.scalar_one_or_none()
    if proposal and proposal.owner_id == current_user.id:
        raise HTTPException(
            status_code=403, detail="Proposal owners cannot review their own proposals"
        )

    existing_review_result = await db.execute(
        select(ExpertReview.id).where(ExpertReview.assignment_id == assignment_id)
    )
    if existing_review_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409, detail="A review already exists for this assignment"
        )

    rubric = await _active_rubric_for_assignment(db, assignment)
    criteria_result = await db.execute(
        select(RubricCriterion)
        .where(RubricCriterion.rubric_version_id == rubric.id)
        .order_by(RubricCriterion.order.asc())
    )
    criteria = criteria_result.scalars().all()
    by_id = {criterion.id: criterion for criterion in criteria}
    by_key = {
        criterion.criterion_key: criterion
        for criterion in criteria
        if criterion.criterion_key
    }

    submitted: dict[str, tuple[RubricCriterion, CriterionScoreRequest]] = {}
    for item in body.criterion_scores:
        key = item.criterion_id.strip()
        criterion = by_id.get(key) or by_key.get(key)
        if criterion is None:
            raise HTTPException(
                status_code=422,
                detail=f"Criterion '{key}' does not belong to the active rubric",
            )
        if criterion.id in submitted:
            raise HTTPException(
                status_code=422,
                detail=f"Criterion '{key}' was submitted more than once",
            )
        if item.score > criterion.maximum:
            raise HTTPException(
                status_code=422,
                detail=f"Score for '{criterion.criterion}' exceeds maximum {criterion.maximum}",
            )
        submitted[criterion.id] = (criterion, item)

    missing = [
        criterion.criterion_key or criterion.id
        for criterion in criteria
        if criterion.id not in submitted
    ]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={"code": "incomplete_review", "missing_criteria": missing},
        )

    calculated_total = round(
        sum(float(item.score) for _, item in submitted.values()), 2
    )
    if abs(calculated_total - body.total_score) > 0.01:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "review_total_mismatch",
                "submitted_total": body.total_score,
                "calculated_total": calculated_total,
            },
        )
    if calculated_total > rubric.total_marks:
        raise HTTPException(
            status_code=422, detail="Review total exceeds the rubric maximum"
        )

    validation_case = None
    validation_study = None
    if assignment.validation_case_id:
        case_result = await db.execute(
            select(ValidationCase).where(
                ValidationCase.id == assignment.validation_case_id
            )
        )
        validation_case = case_result.scalar_one_or_none()
        if validation_case is None:
            raise HTTPException(
                status_code=409, detail="Validation case is missing for this assignment"
            )
        study_result = await db.execute(
            select(ValidationStudy).where(
                ValidationStudy.id == validation_case.study_id
            )
        )
        validation_study = study_result.scalar_one_or_none()
        if validation_study is None:
            raise HTTPException(
                status_code=409, detail="Validation study is missing for this assignment"
            )
        if validation_study.status not in {"active", "frozen"}:
            raise HTTPException(
                status_code=409,
                detail="Shadow-pilot reviews can only be submitted while the study is active or frozen",
            )
        _validate_shadow_annotations(submitted)

    now = datetime.now(timezone.utc)
    review = ExpertReview(
        assignment_id=assignment_id,
        total_score=calculated_total,
        recommendation=body.recommendation.value,
        notes=body.notes,
        annotation_protocol_version=(
            validation_study.protocol_version if validation_study else None
        ),
        annotation_rulebook_version=(
            validation_study.annotation_rulebook_version
            if validation_study
            else None
        ),
        model_output_visible_at_submission=not bool(
            validation_study and validation_study.shadow_mode and assignment.is_blind
        ),
        is_submitted=True,
        submitted_at=now,
    )
    db.add(review)
    await db.flush()
    for criterion, item in submitted.values():
        db.add(
            ExpertCriterionScore(
                review_id=review.id,
                rubric_criterion_id=criterion.id,
                score=item.score,
                confidence=item.confidence,
                evidence_coverage=item.evidence_coverage,
                rationale=item.rationale,
                page_references=item.page_references,
            )
        )

    assignment.status = AssignmentStatus.COMPLETED.value
    assignment.completed_at = now
    if validation_case is not None and validation_study is not None:
        completed_result = await db.execute(
            select(func.count())
            .select_from(ReviewerAssignment)
            .where(
                ReviewerAssignment.validation_case_id == validation_case.id,
                ReviewerAssignment.status == AssignmentStatus.COMPLETED.value,
            )
        )
        completed_count = int(completed_result.scalar() or 0)
        validation_case.status = (
            "ready"
            if completed_count >= validation_study.minimum_reviews_per_case
            else "under_review"
        )
    await _record_review_monitoring(
        db, assignment, calculated_total, body.recommendation.value
    )
    await create_audit_event(
        db,
        event_type="review.submitted",
        user=current_user,
        resource_type="reviewer_assignment",
        resource_id=assignment_id,
        details={
            "proposal_id": assignment.proposal_id,
            "recommendation": body.recommendation.value,
            "total_score": calculated_total,
            "rubric_version": rubric.version,
            "validation_case_id": assignment.validation_case_id,
            "shadow_mode": bool(validation_study and validation_study.shadow_mode),
            "model_output_visible_at_submission": review.model_output_visible_at_submission,
            "annotation_protocol_version": review.annotation_protocol_version,
            "annotation_rulebook_version": review.annotation_rulebook_version,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return ReviewSubmitResponse(
        assignment_id=assignment_id,
        status="submitted",
        message="Review submitted successfully",
    )


@router.get("/proposals/{proposal_id}", response_model=ProposalReviewsResponse)
async def list_proposal_reviews(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_proposal_for_user(db, current_user, proposal_id, conceal_existence=True)
    if await reviewer_model_output_is_blinded(db, current_user, proposal_id):
        return ProposalReviewsResponse(proposal_id=proposal_id, reviews=[])
    assignments_result = await db.execute(
        select(ReviewerAssignment).where(ReviewerAssignment.proposal_id == proposal_id)
    )
    assignments = assignments_result.scalars().all()
    responses: list[ExpertReviewResponse] = []
    for assignment in assignments:
        review_result = await db.execute(
            select(ExpertReview).where(
                ExpertReview.assignment_id == assignment.id,
                ExpertReview.is_submitted.is_(True),
            )
        )
        review = review_result.scalar_one_or_none()
        if review is None:
            continue
        score_result = await db.execute(
            select(ExpertCriterionScore, RubricCriterion)
            .join(
                RubricCriterion,
                RubricCriterion.id == ExpertCriterionScore.rubric_criterion_id,
            )
            .where(ExpertCriterionScore.review_id == review.id)
            .order_by(RubricCriterion.order.asc())
        )
        score_responses = [
            CriterionScoreResponse(
                criterion_id=criterion.id,
                criterion_key=criterion.criterion_key,
                criterion=criterion.criterion,
                maximum=criterion.maximum,
                score=score.score,
                confidence=score.confidence,
                evidence_coverage=score.evidence_coverage,
                rationale=score.rationale,
                page_references=score.page_references or [],
            )
            for score, criterion in score_result.all()
        ]
        version_result = await db.execute(
            select(ProposalVersion.version_number).where(
                ProposalVersion.id == assignment.proposal_version_id
            )
        )
        version_number = version_result.scalar_one_or_none()
        if version_number is None:
            continue
        responses.append(
            ExpertReviewResponse(
                id=review.id,
                assignment_id=assignment.id,
                reviewer_id=assignment.reviewer_id,
                reviewer_role=assignment.role,
                proposal_version_id=assignment.proposal_version_id,
                proposal_version_number=version_number,
                total_score=review.total_score,
                recommendation=review.recommendation,
                notes=review.notes,
                submitted_at=review.submitted_at,
                criterion_scores=score_responses,
            )
        )
    return ProposalReviewsResponse(proposal_id=proposal_id, reviews=responses)
