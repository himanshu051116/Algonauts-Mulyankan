import arq
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.config import settings
from app.database import get_db
from app.domain import ProposalStatus
from app.models.proposal import (
    ModelRun,
    Proposal,
    ProposalDocument,
    ProposalVersion,
)
from app.models.user import User, UserRole
from app.schemas.evaluation import EvaluationResponse, EvaluationRerunResponse
from app.services.access import (
    get_proposal_for_user,
    reviewer_model_output_is_blinded,
)
from app.services.audit import create_audit_event
from app.services.evaluation_payload import public_gate_payload, public_scoring_payload
from app.services.schemes import ensure_proposal_active_scheme

router = APIRouter()


@router.get("/{proposal_id}", response_model=EvaluationResponse)
async def get_evaluation(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    proposal = await get_proposal_for_user(
        db,
        current_user,
        proposal_id,
        conceal_existence=True,
    )
    await ensure_proposal_active_scheme(db, proposal)
    if await reviewer_model_output_is_blinded(db, current_user, proposal_id):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "shadow_review_blinded",
                "message": (
                    "Model output is hidden until the assigned blind expert review "
                    "has been submitted."
                ),
            },
        )

    # Find latest version for this proposal
    version_result = await db.execute(
        select(ProposalVersion.id)
        .where(ProposalVersion.proposal_id == proposal_id)
        .order_by(ProposalVersion.version_number.desc())
        .limit(1)
    )
    latest_version_id = version_result.scalar_one_or_none()
    if not latest_version_id:
        return EvaluationResponse(proposal_id=proposal_id, status="draft")

    # Find the latest model run for this version
    model_run_result = await db.execute(
        select(ModelRun)
        .where(ModelRun.proposal_version_id == latest_version_id)
        .order_by(ModelRun.created_at.desc())
        .limit(1)
    )
    model_run = model_run_result.scalar_one_or_none()

    if not model_run:
        if proposal.status == ProposalStatus.ERROR.value:
            return EvaluationResponse(
                proposal_id=proposal_id,
                status="error",
                error_message=(
                    "Evaluation failed during preflight before a model run was created."
                ),
            )
        return EvaluationResponse(proposal_id=proposal_id, status="pending")

    payload = model_run.evaluation_payload or {}
    safe_scoring = public_scoring_payload(
        payload.get("scoring"),
        scoring_status=model_run.scoring_status,
        total_score=model_run.total_score,
        diagnostic_score=model_run.diagnostic_score,
        abstention_reason=model_run.abstention_reason,
    )
    safe_gate = public_gate_payload(
        payload.get("document_gate"),
        persisted_gate=model_run.gate_result,
        scoring_status=model_run.scoring_status,
    )
    return EvaluationResponse(
        proposal_id=proposal_id,
        status="error" if model_run.status == "failed" else ("completed" if model_run.status == "completed" else model_run.status),
        model_run_id=model_run.id,
        rule_evaluation=payload.get("rule_evaluation"),
        scoring=safe_scoring,
        document_audit=payload.get("document_audit"),
        document_gate=safe_gate,
        prior_project_check=payload.get("prior_project_check"),
        engine_version=payload.get("engine_version"),
        input_checksum=model_run.input_checksum,
        output_checksum=model_run.output_checksum,
        started_at=model_run.started_at,
        completed_at=model_run.completed_at,
        error_message=model_run.error_message,
    )


@router.post("/{proposal_id}/rerun", response_model=EvaluationRerunResponse)
async def rerun_evaluation(
    proposal_id: str,
    request: Request,
    current_user: User = Depends(require_role(UserRole.ML_ENGINEER, UserRole.ADMINISTRATOR)),
    db: AsyncSession = Depends(get_db),
):
    proposal_result = await db.execute(
        select(Proposal).where(Proposal.id == proposal_id).with_for_update()
    )
    proposal = proposal_result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status in {
        ProposalStatus.APPROVED.value,
        ProposalStatus.REJECTED.value,
        ProposalStatus.WITHDRAWN.value,
    }:
        raise HTTPException(
            status_code=409, detail="Finalised or withdrawn proposals cannot be re-evaluated"
        )
    allowed_statuses = {
        ProposalStatus.SUBMITTED.value,
        ProposalStatus.ERROR.value,
        ProposalStatus.HUMAN_REVIEW.value,
        ProposalStatus.ADJUDICATION.value,
        ProposalStatus.COMMITTEE_REVIEW.value,
    }
    if proposal.status not in allowed_statuses:
        raise HTTPException(
            status_code=409,
            detail="The proposal must be submitted before evaluation can be rerun",
        )

    scheme = await ensure_proposal_active_scheme(db, proposal)

    version_result = await db.execute(
        select(ProposalVersion).where(
            ProposalVersion.proposal_id == proposal_id,
            ProposalVersion.version_number == proposal.current_version,
        )
    )
    version = version_result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=409, detail="Current proposal version is missing")

    document_result = await db.execute(
        select(ProposalDocument.id)
        .where(
            ProposalDocument.proposal_version_id == version.id,
            ProposalDocument.is_primary.is_(True),
            ProposalDocument.document_role == "main_proposal",
            ProposalDocument.superseded_at.is_(None),
            ProposalDocument.extracted_text.isnot(None),
        )
        .limit(1)
    )
    if document_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=409,
            detail="The current proposal version has no extracted primary document",
        )

    previous_status = proposal.status
    proposal.status = ProposalStatus.EVALUATING.value

    await create_audit_event(
        db,
        event_type="evaluation.rerun_requested",
        user=current_user,
        resource_type="proposal",
        resource_id=proposal_id,
        details={"scheme_code": scheme.code},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()

    try:
        pool = await arq.create_pool(settings.arq_redis_settings)
        try:
            await pool.enqueue_job(
                "evaluate_proposal",
                proposal_id,
                scheme_code=scheme.code,
                trigger_user_id=current_user.id,
                rerun_reason="manual_rerun",
            )
        finally:
            close_pool = getattr(pool, "aclose", None)
            if close_pool is None:
                close_pool = pool.close
            await close_pool()
    except Exception as exc:
        proposal.status = (
            previous_status
            if previous_status in {status.value for status in ProposalStatus}
            else ProposalStatus.ERROR.value
        )
        await create_audit_event(
            db,
            event_type="evaluation.rerun_queue_failed",
            user=current_user,
            resource_type="proposal",
            resource_id=proposal_id,
            details={"exception_type": type(exc).__name__},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await db.commit()
        raise HTTPException(
            status_code=503,
            detail="Evaluation queue is temporarily unavailable; the proposal state was preserved",
        ) from exc

    return EvaluationRerunResponse(
        proposal_id=proposal_id,
        status="queued",
        message="Evaluation queued for background processing",
    )
