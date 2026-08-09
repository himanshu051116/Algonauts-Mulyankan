"""Central proposal/evaluation access-control policy."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.proposal import (
    Proposal,
    ReviewerAssignment,
    ValidationCase,
    ValidationStudy,
)
from app.models.user import User, UserRole


OVERSIGHT_ROLES: frozenset[UserRole] = frozenset(
    {
        UserRole.ADMINISTRATOR,
        UserRole.SCRUTINY_OFFICER,
        UserRole.SENIOR_ADJUDICATOR,
        UserRole.COMMITTEE_SECRETARIAT,
        UserRole.AUDITOR,
        UserRole.ML_ENGINEER,
    }
)

REVIEWER_ROLES: frozenset[UserRole] = frozenset(
    {
        UserRole.TECHNICAL_REVIEWER,
        UserRole.FINANCIAL_REVIEWER,
    }
)


async def user_can_access_proposal(
    db: AsyncSession,
    user: User,
    proposal: Proposal,
) -> bool:
    """Apply least-privilege read access to a proposal and its evaluation."""

    if proposal.owner_id == user.id:
        return True
    if user.role in OVERSIGHT_ROLES:
        return True
    if getattr(user, "role", None) not in REVIEWER_ROLES:
        return False

    assignment_result = await db.execute(
        select(ReviewerAssignment.id)
        .where(
            ReviewerAssignment.proposal_id == proposal.id,
            ReviewerAssignment.reviewer_id == user.id,
            ReviewerAssignment.status != "cancelled",
        )
        .limit(1)
    )
    return assignment_result.scalar_one_or_none() is not None


async def get_proposal_for_user(
    db: AsyncSession,
    user: User,
    proposal_id: str,
    *,
    conceal_existence: bool = False,
) -> Proposal:
    result = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if not await user_can_access_proposal(db, user, proposal):
        if conceal_existence:
            raise HTTPException(status_code=404, detail="Proposal not found")
        raise HTTPException(status_code=403, detail="Access denied")
    return proposal


async def reviewer_model_output_is_blinded(
    db: AsyncSession,
    user: User,
    proposal_id: str,
) -> bool:
    """Return whether a shadow-pilot reviewer must remain blind to model output."""

    if getattr(user, "role", None) not in REVIEWER_ROLES:
        return False
    result = await db.execute(
        select(ReviewerAssignment.id)
        .join(
            ValidationCase,
            ValidationCase.id == ReviewerAssignment.validation_case_id,
        )
        .join(ValidationStudy, ValidationStudy.id == ValidationCase.study_id)
        .where(
            ReviewerAssignment.proposal_id == proposal_id,
            ReviewerAssignment.reviewer_id == user.id,
            ReviewerAssignment.is_blind.is_(True),
            ReviewerAssignment.status.notin_(["completed", "cancelled"]),
            ValidationStudy.shadow_mode.is_(True),
            ValidationStudy.status.in_(["active", "frozen"]),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def enforce_shadow_review_blindness(
    db: AsyncSession,
    user: User,
    proposal_id: str,
    *,
    detail: str = "This information is hidden until the assigned blind expert review is submitted",
) -> None:
    """Block outcome-derived information while an expert label must stay independent."""

    if await reviewer_model_output_is_blinded(db, user, proposal_id):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "shadow_review_blinded",
                "message": detail,
            },
        )
