from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.config import settings
from app.database import get_db
from app.domain import (
    ProposalStatus,
    proposal_transition_allowed,
)
from app.models.proposal import (
    Adjudication,
    CommitteeDecision,
    ExpertReview,
    ModelMonitoringMetric,
    ModelRun,
    Proposal,
    ProposalVersion,
    ReviewerAssignment,
    RubricCriterion,
)
from app.models.user import User, UserRole
from app.schemas.governance import (
    AdjudicationCreate,
    AdjudicationListResponse,
    AdjudicationResponse,
    CommitteeDecisionCreate,
    CommitteeDecisionResponse,
    ModelMonitoringMetricResponse,
    ModelMonitoringRunResponse,
)
from app.services.access import enforce_shadow_review_blindness, get_proposal_for_user
from app.services.audit import create_audit_event
from app.services.signing import sign_integrity_payload

router = APIRouter()


def _adjudication_response(item: Adjudication) -> AdjudicationResponse:
    return AdjudicationResponse.model_validate(item)


def _committee_response(item: CommitteeDecision) -> CommitteeDecisionResponse:
    return CommitteeDecisionResponse.model_validate(item)


async def _current_version(db: AsyncSession, proposal: Proposal) -> ProposalVersion:
    result = await db.execute(
        select(ProposalVersion).where(
            ProposalVersion.proposal_id == proposal.id,
            ProposalVersion.version_number == proposal.current_version,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(
            status_code=409, detail="Current proposal version is missing"
        )
    return version


async def _completed_reviews(
    db: AsyncSession,
    proposal_version_id: str,
) -> list[tuple[ExpertReview, str]]:
    result = await db.execute(
        select(ExpertReview, ReviewerAssignment.role)
        .join(
            ReviewerAssignment,
            ReviewerAssignment.id == ExpertReview.assignment_id,
        )
        .where(
            ReviewerAssignment.proposal_version_id == proposal_version_id,
            ExpertReview.is_submitted.is_(True),
        )
    )
    return [(row[0], row[1]) for row in result.all()]


@router.get(
    "/monitoring/model-runs/{model_run_id}",
    response_model=ModelMonitoringRunResponse,
)
async def get_model_run_monitoring(
    model_run_id: str,
    current_user: User = Depends(
        require_role(
            UserRole.ML_ENGINEER,
            UserRole.ADMINISTRATOR,
            UserRole.AUDITOR,
            UserRole.SCRUTINY_OFFICER,
        )
    ),
    db: AsyncSession = Depends(get_db),
) -> ModelMonitoringRunResponse:
    run_result = await db.execute(
        select(ModelRun).where(ModelRun.id == model_run_id)
    )
    model_run = run_result.scalar_one_or_none()
    if model_run is None:
        raise HTTPException(status_code=404, detail="Model run not found")
    metric_result = await db.execute(
        select(ModelMonitoringMetric)
        .where(ModelMonitoringMetric.model_run_id == model_run.id)
        .order_by(ModelMonitoringMetric.recorded_at.asc())
    )
    return ModelMonitoringRunResponse(
        model_run_id=model_run.id,
        proposal_version_id=model_run.proposal_version_id,
        model_score=model_run.total_score,
        abstention_reason=model_run.abstention_reason,
        metrics=[
            ModelMonitoringMetricResponse.model_validate(metric)
            for metric in metric_result.scalars().all()
        ],
    )


@router.get(
    "/proposals/{proposal_id}/adjudications",
    response_model=AdjudicationListResponse,
)
async def list_adjudications(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_proposal_for_user(db, current_user, proposal_id, conceal_existence=True)
    await enforce_shadow_review_blindness(
        db,
        current_user,
        proposal_id,
        detail="Adjudications are hidden until the blind expert review is submitted",
    )
    result = await db.execute(
        select(Adjudication)
        .where(Adjudication.proposal_id == proposal_id)
        .order_by(Adjudication.created_at.desc())
    )
    return AdjudicationListResponse(
        proposal_id=proposal_id,
        adjudications=[_adjudication_response(item) for item in result.scalars().all()],
    )


@router.post(
    "/proposals/{proposal_id}/adjudications",
    status_code=status.HTTP_201_CREATED,
    response_model=AdjudicationResponse,
)
async def create_adjudication(
    proposal_id: str,
    body: AdjudicationCreate,
    request: Request,
    current_user: User = Depends(
        require_role(UserRole.SENIOR_ADJUDICATOR, UserRole.ADMINISTRATOR)
    ),
    db: AsyncSession = Depends(get_db),
):
    proposal_result = await db.execute(
        select(Proposal).where(Proposal.id == proposal_id).with_for_update()
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
            detail="Adjudication is only available after human review",
        )

    version = await _current_version(db, proposal)
    completed = await _completed_reviews(db, version.id)
    if len(completed) < 2:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "insufficient_reviews",
                "required": 2,
                "completed": len(completed),
            },
        )

    criterion: RubricCriterion | None = None
    if body.criterion_id:
        criterion_result = await db.execute(
            select(RubricCriterion).where(
                RubricCriterion.rubric_version_id == version.rubric_version_id,
                (RubricCriterion.id == body.criterion_id)
                | (RubricCriterion.criterion_key == body.criterion_id),
            )
        )
        criterion = criterion_result.scalar_one_or_none()
        if criterion is None:
            raise HTTPException(
                status_code=422,
                detail="The adjudicated criterion does not belong to this proposal rubric",
            )
        if body.resolved_score is not None and body.resolved_score > criterion.maximum:
            raise HTTPException(
                status_code=422,
                detail=f"Resolved score exceeds criterion maximum {criterion.maximum}",
            )

    item = Adjudication(
        proposal_id=proposal.id,
        proposal_version_id=version.id,
        adjudicator_id=current_user.id,
        criterion_id=criterion.id if criterion else None,
        reason=body.reason,
        resolved_score=body.resolved_score,
    )
    db.add(item)
    await db.flush()

    previous_status = proposal.status
    if proposal.status != ProposalStatus.ADJUDICATION.value:
        if not proposal_transition_allowed(
            proposal.status, ProposalStatus.ADJUDICATION
        ):
            raise HTTPException(
                status_code=409, detail="Invalid proposal status transition"
            )
        proposal.status = ProposalStatus.ADJUDICATION.value

    await create_audit_event(
        db,
        event_type="adjudication.created",
        user=current_user,
        resource_type="adjudication",
        resource_id=item.id,
        details={
            "proposal_id": proposal.id,
            "proposal_version_id": version.id,
            "criterion_id": item.criterion_id,
            "resolved_score": item.resolved_score,
            "status_from": previous_status,
            "status_to": proposal.status,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    await db.refresh(item)
    return _adjudication_response(item)


@router.get(
    "/proposals/{proposal_id}/committee-decision",
    response_model=CommitteeDecisionResponse,
)
async def get_committee_decision(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    proposal = await get_proposal_for_user(
        db, current_user, proposal_id, conceal_existence=True
    )
    await enforce_shadow_review_blindness(
        db,
        current_user,
        proposal_id,
        detail="Committee outcomes are hidden until the blind expert review is submitted",
    )
    version = await _current_version(db, proposal)
    result = await db.execute(
        select(CommitteeDecision).where(
            CommitteeDecision.proposal_version_id == version.id
        )
    )
    decision = result.scalar_one_or_none()
    if decision is None:
        raise HTTPException(status_code=404, detail="Committee decision not found")
    return _committee_response(decision)


@router.get("/proposals/{proposal_id}/committee-decision/export")
async def export_committee_decision(
    proposal_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a controlled integrity-signed decision record.

    The HMAC envelope detects later modification but is not a legal digital
    signature. Institutional deployments may replace it with PKI signing.
    """

    if len(settings.audit_export_signing_key) < 32:
        raise HTTPException(
            status_code=503, detail="Decision export signing is not configured"
        )
    proposal = await get_proposal_for_user(
        db, current_user, proposal_id, conceal_existence=True
    )
    await enforce_shadow_review_blindness(
        db,
        current_user,
        proposal_id,
        detail="Committee outcomes are hidden until the blind expert review is submitted",
    )
    version = await _current_version(db, proposal)
    decision_result = await db.execute(
        select(CommitteeDecision).where(
            CommitteeDecision.proposal_version_id == version.id
        )
    )
    decision = decision_result.scalar_one_or_none()
    if decision is None:
        raise HTTPException(status_code=404, detail="Committee decision not found")

    model_result = await db.execute(
        select(ModelRun)
        .where(
            ModelRun.proposal_version_id == version.id,
            ModelRun.status == "completed",
        )
        .order_by(ModelRun.completed_at.desc(), ModelRun.created_at.desc())
        .limit(1)
    )
    model_run = model_result.scalar_one_or_none()
    completed_reviews = await _completed_reviews(db, version.id)
    payload = {
        "schema_version": "mulyankan-committee-decision-export-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": (
            "Controlled integrity export. The HMAC is not a legal digital "
            "signature or public-key certificate."
        ),
        "proposal": {
            "id": proposal.id,
            "title": version.title or proposal.title,
            "status": proposal.status,
            "version_id": version.id,
            "version_number": version.version_number,
            "content_hash": version.content_hash,
            "document_hash": version.document_hash,
            "rubric_version_id": version.rubric_version_id,
            "guideline_version_id": version.guideline_version_id,
        },
        "automated_scrutiny": {
            "model_run_id": model_run.id if model_run else None,
            "model_version_id": model_run.model_version_id if model_run else None,
            "total_score": model_run.total_score if model_run else None,
            "abstention_reason": model_run.abstention_reason if model_run else None,
            "input_checksum": model_run.input_checksum if model_run else None,
            "output_checksum": model_run.output_checksum if model_run else None,
        },
        "expert_reviews": [
            {
                "review_id": review.id,
                "reviewer_role": role,
                "total_score": review.total_score,
                "recommendation": review.recommendation,
                "submitted_at": (
                    review.submitted_at.astimezone(timezone.utc).isoformat()
                    if review.submitted_at
                    else None
                ),
            }
            for review, role in completed_reviews
        ],
        "committee_decision": {
            "id": decision.id,
            "decision": decision.decision,
            "decision_notes": decision.decision_notes,
            "decided_by": decision.decided_by,
            "model_score_at_decision": decision.model_score_at_decision,
            "expert_score_at_decision": decision.expert_score_at_decision,
            "decided_at": decision.decided_at.astimezone(timezone.utc).isoformat(),
        },
    }
    signature = sign_integrity_payload(
        payload, settings.audit_export_signing_key
    )
    envelope = {
        "payload": payload,
        "signature": signature,
    }
    await create_audit_event(
        db,
        event_type="committee.decision_exported",
        user=current_user,
        resource_type="committee_decision",
        resource_id=decision.id,
        details={
            "proposal_id": proposal.id,
            "proposal_version_id": version.id,
            "signature_key_id": signature["key_id"],
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return envelope


@router.post(
    "/proposals/{proposal_id}/committee-decision",
    status_code=status.HTTP_201_CREATED,
    response_model=CommitteeDecisionResponse,
)
async def create_committee_decision(
    proposal_id: str,
    body: CommitteeDecisionCreate,
    request: Request,
    current_user: User = Depends(
        require_role(UserRole.COMMITTEE_SECRETARIAT, UserRole.ADMINISTRATOR)
    ),
    db: AsyncSession = Depends(get_db),
):
    proposal_result = await db.execute(
        select(Proposal).where(Proposal.id == proposal_id).with_for_update()
    )
    proposal = proposal_result.scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status not in {
        ProposalStatus.HUMAN_REVIEW.value,
        ProposalStatus.ADJUDICATION.value,
        ProposalStatus.COMMITTEE_REVIEW.value,
    }:
        raise HTTPException(
            status_code=409,
            detail="Committee decision is not available in the current proposal status",
        )

    version = await _current_version(db, proposal)
    existing_result = await db.execute(
        select(CommitteeDecision.id).where(
            CommitteeDecision.proposal_version_id == version.id
        )
    )
    if existing_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="A committee decision already exists for this proposal version",
        )

    completed = await _completed_reviews(db, version.id)
    completed_roles = {role for _, role in completed}
    adjudication_result = await db.execute(
        select(func.count(Adjudication.id)).where(
            Adjudication.proposal_version_id == version.id
        )
    )
    adjudication_count = int(adjudication_result.scalar() or 0)
    required_roles = {"technical", "financial"}
    if not required_roles.issubset(completed_roles) and adjudication_count == 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "review_policy_not_satisfied",
                "required_roles": sorted(required_roles),
                "completed_roles": sorted(completed_roles),
                "adjudication_count": adjudication_count,
            },
        )

    model_result = await db.execute(
        select(ModelRun)
        .where(
            ModelRun.proposal_version_id == version.id,
            ModelRun.status == "completed",
        )
        .order_by(ModelRun.completed_at.desc(), ModelRun.created_at.desc())
        .limit(1)
    )
    model_run = model_result.scalar_one_or_none()
    model_score = model_run.total_score if model_run else None
    expert_scores = [
        float(review.total_score)
        for review, _ in completed
        if review.total_score is not None
    ]
    expert_score = (
        round(sum(expert_scores) / len(expert_scores), 2) if expert_scores else None
    )

    if proposal.status != ProposalStatus.COMMITTEE_REVIEW.value:
        if not proposal_transition_allowed(
            proposal.status, ProposalStatus.COMMITTEE_REVIEW
        ):
            raise HTTPException(
                status_code=409, detail="Invalid committee review transition"
            )
        proposal.status = ProposalStatus.COMMITTEE_REVIEW.value

    target_status = ProposalStatus(body.decision.value)
    if not proposal_transition_allowed(proposal.status, target_status):
        raise HTTPException(status_code=409, detail="Invalid final decision transition")
    previous_status = proposal.status
    proposal.status = target_status.value


    if model_run is not None and model_score is not None:
        if expert_score is not None:
            delta = float(expert_score) - float(model_score)
            db.add(
                ModelMonitoringMetric(
                    model_run_id=model_run.id,
                    metric_name="committee_expert_score_delta",
                    metric_value=delta,
                )
            )
            db.add(
                ModelMonitoringMetric(
                    model_run_id=model_run.id,
                    metric_name="committee_expert_abs_error",
                    metric_value=abs(delta),
                )
            )
        expected_decision = (
            "approved"
            if model_score >= 80
            else "revision_required"
            if model_score >= 60
            else "rejected"
        )
        db.add(
            ModelMonitoringMetric(
                model_run_id=model_run.id,
                metric_name="committee_decision_disagreement",
                metric_value=(
                    0.0 if expected_decision == body.decision.value else 1.0
                ),
            )
        )

    decision = CommitteeDecision(
        proposal_id=proposal.id,
        proposal_version_id=version.id,
        decision=body.decision.value,
        decision_notes=body.decision_notes,
        decided_by=current_user.id,
        model_score_at_decision=model_score,
        expert_score_at_decision=expert_score,
    )
    db.add(decision)
    await db.flush()

    await create_audit_event(
        db,
        event_type="committee.decision_recorded",
        user=current_user,
        resource_type="committee_decision",
        resource_id=decision.id,
        details={
            "proposal_id": proposal.id,
            "proposal_version_id": version.id,
            "decision": body.decision.value,
            "model_score": model_score,
            "expert_score": expert_score,
            "status_from": previous_status,
            "status_to": proposal.status,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    await db.refresh(decision)
    return _committee_response(decision)
