"""Audit router: paginated query, verification, and signed controlled exports."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.proposal import AuditEvent
from app.models.user import User, UserRole
from app.services.audit import verify_audit_chain
from app.services.signing import sign_integrity_payload

router = APIRouter(tags=["audit"])

AUDITOR_ROLES = {
    UserRole.AUDITOR,
    UserRole.ADMINISTRATOR,
    UserRole.COMMITTEE_SECRETARIAT,
}


def _require_auditor(user: User) -> None:
    if user.role not in AUDITOR_ROLES:
        raise HTTPException(status_code=403, detail="Only auditors can view audit events")


@router.get("/audit/events")
async def list_audit_events(
    resource_type: str | None = Query(None),
    resource_id: str | None = Query(None),
    event_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_auditor(user)
    filters = []
    if resource_type:
        filters.append(AuditEvent.resource_type == resource_type)
    if resource_id:
        filters.append(AuditEvent.resource_id == resource_id)
    if event_type:
        filters.append(AuditEvent.event_type == event_type)

    count_result = await db.execute(select(func.count(AuditEvent.id)).where(*filters))
    total = int(count_result.scalar_one())
    result = await db.execute(
        select(AuditEvent)
        .where(*filters)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "events": result.scalars().all(),
    }


@router.get("/audit/verify")
async def verify_audit_events(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_auditor(user)
    result = await db.execute(
        select(AuditEvent).order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
    )
    return verify_audit_chain(list(result.scalars().all()))


@router.get("/audit/export")
async def export_audit_events(
    resource_type: str | None = Query(None),
    resource_id: str | None = Query(None),
    event_type: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a deterministic, HMAC-signed audit export.

    This is a controlled integrity envelope, not a legal digital signature.
    Production startup requires a dedicated secret signing key.
    """
    _require_auditor(user)
    if len(settings.audit_export_signing_key) < 32:
        raise HTTPException(status_code=503, detail="Audit export signing is not configured")

    filters = []
    if resource_type:
        filters.append(AuditEvent.resource_type == resource_type)
    if resource_id:
        filters.append(AuditEvent.resource_id == resource_id)
    if event_type:
        filters.append(AuditEvent.event_type == event_type)
    result = await db.execute(
        select(AuditEvent)
        .where(*filters)
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
    )
    events = list(result.scalars().all())
    verification = verify_audit_chain(events)
    payload = {
        "schema_version": "mulyankan-audit-export-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "event_type": event_type,
        },
        "verification": verification,
        "events": [
            {
                "id": event.id,
                "user_id": event.user_id,
                "event_type": event.event_type,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "details": event.details or {},
                "ip_address": event.ip_address,
                "user_agent": event.user_agent,
                "previous_hash": event.previous_hash,
                "event_hash": event.event_hash,
                "created_at": event.created_at.astimezone(timezone.utc).isoformat(),
            }
            for event in events
        ],
    }
    return {
        "payload": payload,
        "signature": sign_integrity_payload(
            payload, settings.audit_export_signing_key
        ),
    }
