"""Active funding scheme policy for the production workflow."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.proposal import FundingScheme, Proposal

ACTIVE_SCHEME_CODES = ("MOC-ST",)


def unsupported_scheme_detail(scheme_code: str | None = None) -> dict:
    detail = {
        "code": "unsupported_scheme",
        "supported_schemes": list(ACTIVE_SCHEME_CODES),
    }
    if scheme_code:
        detail["scheme_code"] = scheme_code
    return detail


def ensure_active_scheme_code(scheme_code: str) -> None:
    if scheme_code not in ACTIVE_SCHEME_CODES:
        raise HTTPException(status_code=422, detail=unsupported_scheme_detail(scheme_code))


async def get_active_scheme_or_422(db: AsyncSession, scheme_code: str) -> FundingScheme:
    ensure_active_scheme_code(scheme_code)
    result = await db.execute(select(FundingScheme).where(FundingScheme.code == scheme_code))
    scheme = result.scalar_one_or_none()
    if not scheme:
        raise HTTPException(status_code=404, detail=f"Scheme '{scheme_code}' not found")
    return scheme


async def ensure_proposal_active_scheme(db: AsyncSession, proposal: Proposal) -> FundingScheme:
    result = await db.execute(select(FundingScheme).where(FundingScheme.id == proposal.scheme_id))
    scheme = result.scalar_one_or_none()
    if not scheme:
        raise HTTPException(status_code=500, detail=f"Funding scheme not found for proposal {proposal.id}")
    ensure_active_scheme_code(scheme.code)
    return scheme
