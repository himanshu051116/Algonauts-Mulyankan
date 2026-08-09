from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.database import get_db
from app.domain import AssignmentStatus
from app.models.proposal import (
    FundingScheme,
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
from app.schemas.validation import (
    ValidationAssignmentCreateRequest,
    ValidationAssignmentResponse,
    ValidationCaseCreateRequest,
    ValidationCaseExcludeRequest,
    ValidationCaseListResponse,
    ValidationCaseResponse,
    ValidationComputeResponse,
    ValidationCriterionFormItem,
    ValidationMetricResponse,
    ValidationReviewFormResponse,
    ValidationStudyCreateRequest,
    ValidationStudyListResponse,
    ValidationStudyResponse,
    ValidationStudyStatusRequest,
    ValidationStudySummaryResponse,
)
from app.services.audit import create_audit_event
from app.services.model_registry import select_active_model_version
from app.services.validation import (
    compute_study_metrics,
    export_study_jsonl,
    latest_study_metrics,
    rubric_definition_hash,
    study_response_data,
    validate_study_frozen_identity,
    validation_readiness,
)

router = APIRouter()

MANAGE_ROLES = (
    UserRole.ADMINISTRATOR,
    UserRole.ML_ENGINEER,
    UserRole.SCRUTINY_OFFICER,
)
READ_ROLES = (
    UserRole.ADMINISTRATOR,
    UserRole.ML_ENGINEER,
    UserRole.SCRUTINY_OFFICER,
    UserRole.AUDITOR,
    UserRole.SENIOR_ADJUDICATOR,
    UserRole.COMMITTEE_SECRETARIAT,
)


async def _study_or_404(db: AsyncSession, study_id: str) -> ValidationStudy:
    result = await db.execute(
        select(ValidationStudy).where(ValidationStudy.id == study_id)
    )
    study = result.scalar_one_or_none()
    if study is None:
        raise HTTPException(status_code=404, detail="Validation study not found")
    return study


async def _case_or_404(db: AsyncSession, case_id: str) -> ValidationCase:
    result = await db.execute(
        select(ValidationCase).where(ValidationCase.id == case_id)
    )
    validation_case = result.scalar_one_or_none()
    if validation_case is None:
        raise HTTPException(status_code=404, detail="Validation case not found")
    return validation_case


async def _study_response(
    db: AsyncSession, study: ValidationStudy
) -> ValidationStudyResponse:
    return ValidationStudyResponse(**(await study_response_data(db, study)))


async def _case_response(
    db: AsyncSession,
    study: ValidationStudy,
    validation_case: ValidationCase,
) -> ValidationCaseResponse:
    version_result = await db.execute(
        select(ProposalVersion, Proposal)
        .join(Proposal, Proposal.id == ProposalVersion.proposal_id)
        .where(ProposalVersion.id == validation_case.proposal_version_id)
    )
    version, proposal = version_result.one()
    assignment_result = await db.execute(
        select(ReviewerAssignment).where(
            ReviewerAssignment.validation_case_id == validation_case.id
        )
    )
    assignments = list(assignment_result.scalars().all())
    return ValidationCaseResponse(
        id=validation_case.id,
        study_id=validation_case.study_id,
        proposal_id=validation_case.proposal_id,
        proposal_version_id=validation_case.proposal_version_id,
        proposal_version_number=version.version_number,
        proposal_title=version.title or proposal.title,
        model_run_id=validation_case.model_run_id,
        partition=validation_case.partition,
        status=validation_case.status,
        exclusion_reason=validation_case.exclusion_reason,
        included_by=validation_case.included_by,
        included_at=validation_case.included_at,
        comparison_ready_at=validation_case.comparison_ready_at,
        assigned_reviewers=len(assignments),
        completed_reviews=sum(
            assignment.status == AssignmentStatus.COMPLETED.value
            for assignment in assignments
        ),
        minimum_reviews_required=study.minimum_reviews_per_case,
        model_output_blinded=study.shadow_mode,
    )


@router.post("/studies", response_model=ValidationStudyResponse, status_code=201)
async def create_validation_study(
    body: ValidationStudyCreateRequest,
    request: Request,
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    scheme_result = await db.execute(
        select(FundingScheme).where(
            FundingScheme.code == body.scheme_code,
            FundingScheme.is_active.is_(True),
        )
    )
    scheme = scheme_result.scalar_one_or_none()
    if scheme is None:
        raise HTTPException(status_code=422, detail="Active scheme not found")

    try:
        model = await select_active_model_version(db, body.scheme_code)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    rubric_result = await db.execute(
        select(RubricVersion).where(RubricVersion.id == model.rubric_version_id)
    )
    rubric = rubric_result.scalar_one()

    frozen_rubric_hash = await rubric_definition_hash(db, rubric.id)

    policy = dict(body.recommendation_policy)
    if policy:
        approved_min = policy.get("approved_min")
        revision_min = policy.get("revision_min")
        if not isinstance(approved_min, (int, float)) or not isinstance(
            revision_min, (int, float)
        ):
            raise HTTPException(
                status_code=422,
                detail="Recommendation policy requires numeric approved_min and revision_min",
            )
        if not (0 <= float(revision_min) < float(approved_min) <= 100):
            raise HTTPException(
                status_code=422,
                detail="Recommendation policy must satisfy 0 <= revision_min < approved_min <= 100",
            )
        policy.setdefault("classification", "study-specific-observational")

    study = ValidationStudy(
        name=body.name.strip(),
        description=body.description,
        scheme_id=scheme.id,
        rubric_version_id=rubric.id,
        model_version_id=model.id,
        model_artifact_hash=model.artifact_hash,
        rubric_definition_hash=frozen_rubric_hash,
        protocol_version=body.protocol_version.strip(),
        annotation_rulebook_version=body.annotation_rulebook_version.strip(),
        status="draft",
        shadow_mode=body.shadow_mode,
        minimum_reviews_per_case=body.minimum_reviews_per_case,
        recommendation_policy=policy,
        created_by=current_user.id,
    )
    db.add(study)
    await db.flush()
    await create_audit_event(
        db,
        event_type="validation.study_created",
        user=current_user,
        resource_type="validation_study",
        resource_id=study.id,
        details={
            "scheme_code": scheme.code,
            "rubric_version": rubric.version,
            "model_name": model.model_name,
            "model_version": model.version,
            "shadow_mode": body.shadow_mode,
            "minimum_reviews_per_case": body.minimum_reviews_per_case,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    await db.refresh(study)
    return await _study_response(db, study)


@router.get("/studies", response_model=ValidationStudyListResponse)
async def list_validation_studies(
    current_user: User = Depends(require_role(*READ_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    del current_user
    result = await db.execute(
        select(ValidationStudy).order_by(ValidationStudy.created_at.desc())
    )
    studies = list(result.scalars().all())
    return ValidationStudyListResponse(
        studies=[await _study_response(db, study) for study in studies]
    )


@router.get("/studies/{study_id}", response_model=ValidationStudySummaryResponse)
async def get_validation_study_summary(
    study_id: str,
    current_user: User = Depends(require_role(*READ_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    del current_user
    study = await _study_or_404(db, study_id)
    snapshot_group_id, computed_at, snapshots = await latest_study_metrics(db, study.id)
    readiness = await validation_readiness(db, study)
    return ValidationStudySummaryResponse(
        study=await _study_response(db, study),
        readiness=readiness,
        snapshot_group_id=snapshot_group_id,
        metrics=[
            ValidationMetricResponse(
                name=(
                    snapshot.metric_name
                    if snapshot.partition == "all"
                    else f"{snapshot.partition}:{snapshot.metric_name}"
                ),
                value=snapshot.metric_value,
                sample_size=snapshot.sample_size,
                details=snapshot.details or {},
            )
            for snapshot in snapshots
        ],
        computed_at=computed_at,
    )


@router.patch("/studies/{study_id}/status", response_model=ValidationStudyResponse)
async def update_validation_study_status(
    study_id: str,
    body: ValidationStudyStatusRequest,
    request: Request,
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    study = await _study_or_404(db, study_id)
    try:
        await validate_study_frozen_identity(db, study)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    transitions = {
        "draft": {"active", "archived"},
        "active": {"frozen", "archived"},
        "frozen": {"completed", "archived"},
        "completed": {"archived"},
        "archived": set(),
    }
    if body.status == study.status:
        return await _study_response(db, study)
    if body.status not in transitions.get(study.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Study cannot transition from {study.status} to {body.status}",
        )
    if body.status == "completed":
        incomplete_result = await db.execute(
            select(func.count())
            .select_from(ValidationCase)
            .where(
                ValidationCase.study_id == study.id,
                ValidationCase.status.notin_(["compared", "excluded"]),
            )
        )
        if int(incomplete_result.scalar() or 0) > 0:
            raise HTTPException(
                status_code=409,
                detail="All included cases must be compared or excluded before completion",
            )

    now = datetime.now(timezone.utc)
    study.status = body.status
    if body.status == "active":
        study.activated_at = study.activated_at or now
    elif body.status == "frozen":
        study.frozen_at = now
    elif body.status == "completed":
        study.completed_at = now
    await create_audit_event(
        db,
        event_type="validation.study_status_changed",
        user=current_user,
        resource_type="validation_study",
        resource_id=study.id,
        details={"status": body.status},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    await db.refresh(study)
    return await _study_response(db, study)


@router.post(
    "/studies/{study_id}/cases", response_model=ValidationCaseResponse, status_code=201
)
async def add_validation_case(
    study_id: str,
    body: ValidationCaseCreateRequest,
    request: Request,
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    study = await _study_or_404(db, study_id)
    try:
        await validate_study_frozen_identity(db, study)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if study.status not in {"draft", "active"}:
        raise HTTPException(
            status_code=409, detail="Cases cannot be added after the study is frozen"
        )
    proposal_result = await db.execute(
        select(Proposal).where(Proposal.id == body.proposal_id)
    )
    proposal = proposal_result.scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.scheme_id != study.scheme_id:
        raise HTTPException(
            status_code=409, detail="Proposal scheme does not match the validation study"
        )

    version_query = select(ProposalVersion).where(
        ProposalVersion.proposal_id == proposal.id
    )
    if body.proposal_version_number is None:
        version_query = version_query.where(
            ProposalVersion.version_number == proposal.current_version
        )
    else:
        version_query = version_query.where(
            ProposalVersion.version_number == body.proposal_version_number
        )
    version_result = await db.execute(version_query)
    version = version_result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Proposal version not found")

    model_run_result = await db.execute(
        select(ModelRun)
        .where(
            ModelRun.proposal_version_id == version.id,
            ModelRun.model_version_id == study.model_version_id,
            ModelRun.status == "completed",
        )
        .order_by(ModelRun.completed_at.desc(), ModelRun.created_at.desc())
        .limit(1)
    )
    model_run = model_run_result.scalar_one_or_none()
    if model_run is None:
        raise HTTPException(
            status_code=409,
            detail="No completed model run matching the frozen study model exists for this version",
        )

    validation_case = ValidationCase(
        study_id=study.id,
        proposal_id=proposal.id,
        proposal_version_id=version.id,
        model_run_id=model_run.id,
        partition=body.partition,
        status="queued",
        included_by=current_user.id,
    )
    db.add(validation_case)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "This proposal is already represented in the study. Multiple versions "
                "of one proposal cannot cross validation partitions."
            ),
        ) from exc

    await create_audit_event(
        db,
        event_type="validation.case_added",
        user=current_user,
        resource_type="validation_case",
        resource_id=validation_case.id,
        details={
            "study_id": study.id,
            "proposal_id": proposal.id,
            "proposal_version_id": version.id,
            "model_run_id": model_run.id,
            "partition": body.partition,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    await db.refresh(validation_case)
    return await _case_response(db, study, validation_case)


@router.patch("/cases/{case_id}/exclude", response_model=ValidationCaseResponse)
async def exclude_validation_case(
    case_id: str,
    body: ValidationCaseExcludeRequest,
    request: Request,
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    validation_case = await _case_or_404(db, case_id)
    study = await _study_or_404(db, validation_case.study_id)
    if study.status not in {"draft", "active"}:
        raise HTTPException(
            status_code=409,
            detail="Cases can only be excluded before the study is frozen",
        )
    if validation_case.status == "compared":
        raise HTTPException(
            status_code=409,
            detail="Compared cases cannot be excluded from an active dataset",
        )
    assignment_result = await db.execute(
        select(ReviewerAssignment).where(
            ReviewerAssignment.validation_case_id == validation_case.id,
            ReviewerAssignment.status.notin_(["completed", "cancelled"]),
        )
    )
    pending_assignments = list(assignment_result.scalars().all())
    for assignment in pending_assignments:
        assignment.status = "cancelled"

    validation_case.status = "excluded"
    validation_case.exclusion_reason = body.reason
    await create_audit_event(
        db,
        event_type="validation.case_excluded",
        user=current_user,
        resource_type="validation_case",
        resource_id=validation_case.id,
        details={
            "study_id": study.id,
            "proposal_id": validation_case.proposal_id,
            "reason": body.reason,
            "cancelled_assignments": len(pending_assignments),
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    await db.refresh(validation_case)
    return await _case_response(db, study, validation_case)


@router.get("/studies/{study_id}/cases", response_model=ValidationCaseListResponse)
async def list_validation_cases(
    study_id: str,
    current_user: User = Depends(require_role(*READ_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    del current_user
    study = await _study_or_404(db, study_id)
    result = await db.execute(
        select(ValidationCase)
        .where(ValidationCase.study_id == study.id)
        .order_by(ValidationCase.included_at.desc())
    )
    cases = list(result.scalars().all())
    return ValidationCaseListResponse(
        study_id=study.id,
        cases=[await _case_response(db, study, case) for case in cases],
    )


@router.post(
    "/cases/{case_id}/assignments",
    response_model=ValidationAssignmentResponse,
    status_code=201,
)
async def assign_shadow_reviewer(
    case_id: str,
    body: ValidationAssignmentCreateRequest,
    request: Request,
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    validation_case = await _case_or_404(db, case_id)
    study = await _study_or_404(db, validation_case.study_id)
    if study.status != "active":
        raise HTTPException(
            status_code=409, detail="Reviewers can only be assigned to an active study"
        )
    if validation_case.status == "excluded":
        raise HTTPException(status_code=409, detail="Excluded cases cannot be reviewed")

    reviewer_result = await db.execute(
        select(User).where(User.email == body.reviewer_email)
    )
    reviewer = reviewer_result.scalar_one_or_none()
    if reviewer is None:
        raise HTTPException(status_code=404, detail="Reviewer not found")
    if not reviewer.is_active or not reviewer.is_verified:
        raise HTTPException(status_code=400, detail="Reviewer is not active and verified")
    expected_role = (
        UserRole.TECHNICAL_REVIEWER
        if body.role.value == "technical"
        else UserRole.FINANCIAL_REVIEWER
    )
    if reviewer.role != expected_role:
        raise HTTPException(
            status_code=400,
            detail=f"Reviewer must have role '{expected_role.value}'",
        )
    proposal_result = await db.execute(
        select(Proposal).where(Proposal.id == validation_case.proposal_id)
    )
    proposal = proposal_result.scalar_one()
    if proposal.owner_id == reviewer.id:
        raise HTTPException(
            status_code=400, detail="Proposal owners cannot review their own proposal"
        )

    assignment = ReviewerAssignment(
        proposal_id=validation_case.proposal_id,
        proposal_version_id=validation_case.proposal_version_id,
        validation_case_id=validation_case.id,
        reviewer_id=reviewer.id,
        assigned_by=current_user.id,
        role=body.role.value,
        status=AssignmentStatus.PENDING.value,
        is_blind=study.shadow_mode,
    )
    db.add(assignment)
    validation_case.status = "under_review"
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This reviewer is already assigned to the proposal version",
        ) from exc

    await create_audit_event(
        db,
        event_type="validation.reviewer_assigned",
        user=current_user,
        resource_type="reviewer_assignment",
        resource_id=assignment.id,
        details={
            "study_id": study.id,
            "validation_case_id": validation_case.id,
            "reviewer_id": reviewer.id,
            "role": body.role.value,
            "blind": study.shadow_mode,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return ValidationAssignmentResponse(
        assignment_id=assignment.id,
        validation_case_id=validation_case.id,
        reviewer_id=reviewer.id,
        status=assignment.status,
        blind=assignment.is_blind,
        message="Blind shadow-review assignment created without changing the proposal decision workflow",
    )


@router.get(
    "/assignments/{assignment_id}/form", response_model=ValidationReviewFormResponse
)
async def get_validation_review_form(
    assignment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    assignment_result = await db.execute(
        select(ReviewerAssignment).where(ReviewerAssignment.id == assignment_id)
    )
    assignment = assignment_result.scalar_one_or_none()
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if current_user.role not in READ_ROLES and assignment.reviewer_id != current_user.id:
        raise HTTPException(status_code=404, detail="Assignment not found")

    version_result = await db.execute(
        select(ProposalVersion, Proposal)
        .join(Proposal, Proposal.id == ProposalVersion.proposal_id)
        .where(ProposalVersion.id == assignment.proposal_version_id)
    )
    version, proposal = version_result.one()

    study: ValidationStudy | None = None
    if assignment.validation_case_id:
        case_result = await db.execute(
            select(ValidationCase).where(
                ValidationCase.id == assignment.validation_case_id
            )
        )
        validation_case = case_result.scalar_one_or_none()
        if validation_case:
            study = await _study_or_404(db, validation_case.study_id)
            try:
                await validate_study_frozen_identity(db, study)
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

    rubric_id = study.rubric_version_id if study else version.rubric_version_id
    if rubric_id is None:
        rubric_lookup = await db.execute(
            select(RubricVersion.id)
            .join(ModelVersion, ModelVersion.rubric_version_id == RubricVersion.id)
            .join(ModelRun, ModelRun.model_version_id == ModelVersion.id)
            .where(
                ModelRun.proposal_version_id == version.id,
                ModelRun.status == "completed",
            )
            .order_by(ModelRun.created_at.desc())
            .limit(1)
        )
        rubric_id = rubric_lookup.scalar_one_or_none()
        if rubric_id is None:
            raise HTTPException(status_code=409, detail="Rubric cannot be resolved")

    rubric_result = await db.execute(
        select(RubricVersion).where(RubricVersion.id == rubric_id)
    )
    rubric = rubric_result.scalar_one_or_none()
    if rubric is None:
        raise HTTPException(status_code=409, detail="Rubric cannot be resolved")
    criteria_result = await db.execute(
        select(RubricCriterion)
        .where(RubricCriterion.rubric_version_id == rubric.id)
        .order_by(RubricCriterion.order.asc())
    )
    criteria = list(criteria_result.scalars().all())
    hidden = bool(
        study
        and study.shadow_mode
        and assignment.is_blind
        and assignment.status != AssignmentStatus.COMPLETED.value
    )
    return ValidationReviewFormResponse(
        assignment_id=assignment.id,
        proposal_id=proposal.id,
        proposal_version_id=version.id,
        proposal_version_number=version.version_number,
        proposal_title=version.title or proposal.title,
        reviewer_role=assignment.role,
        validation_case_id=assignment.validation_case_id,
        study_name=study.name if study else None,
        protocol_version=study.protocol_version if study else None,
        annotation_rulebook_version=(
            study.annotation_rulebook_version if study else None
        ),
        shadow_mode=bool(study and study.shadow_mode),
        model_output_hidden=hidden,
        rubric_version=rubric.version,
        total_marks=rubric.total_marks,
        criteria=[
            ValidationCriterionFormItem(
                criterion_id=criterion.id,
                criterion_key=criterion.criterion_key,
                category=criterion.category,
                criterion=criterion.criterion,
                maximum=criterion.maximum,
                description=criterion.description,
                order=criterion.order,
            )
            for criterion in criteria
        ],
    )


@router.post("/studies/{study_id}/compute", response_model=ValidationComputeResponse)
async def compute_validation_metrics(
    study_id: str,
    request: Request,
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    study = await _study_or_404(db, study_id)
    try:
        await validate_study_frozen_identity(db, study)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if study.status not in {"active", "frozen", "completed"}:
        raise HTTPException(
            status_code=409, detail="Activate the study before computing metrics"
        )
    snapshot_group_id, observations, warnings, metrics_written = (
        await compute_study_metrics(db, study)
    )
    await create_audit_event(
        db,
        event_type="validation.metrics_computed",
        user=current_user,
        resource_type="validation_study",
        resource_id=study.id,
        details={
            "snapshot_group_id": snapshot_group_id,
            "compared_cases": len(observations),
            "metrics_written": metrics_written,
            "warnings": warnings,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return ValidationComputeResponse(
        study_id=study.id,
        snapshot_group_id=snapshot_group_id,
        compared_cases=len(observations),
        metrics_written=metrics_written,
        warnings=warnings,
        message=(
            "Shadow-pilot observations computed. These metrics do not establish "
            "scientific validation or alter proposal decisions."
        ),
    )


@router.get("/studies/{study_id}/export")
async def export_validation_dataset(
    study_id: str,
    include_evidence: bool = Query(default=False),
    current_user: User = Depends(
        require_role(UserRole.ADMINISTRATOR, UserRole.ML_ENGINEER, UserRole.AUDITOR)
    ),
    db: AsyncSession = Depends(get_db),
):
    del current_user
    study = await _study_or_404(db, study_id)
    try:
        await validate_study_frozen_identity(db, study)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if study.status not in {"frozen", "completed", "archived"}:
        raise HTTPException(
            status_code=409,
            detail="Freeze the study before exporting a stable expert-labelled dataset",
        )
    content = await export_study_jsonl(
        db, study, include_evidence=include_evidence
    )
    filename = f"mulyankan-validation-{study.id}.jsonl"
    return Response(
        content=content,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
