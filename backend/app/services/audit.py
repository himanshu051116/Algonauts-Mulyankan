"""Tamper-evident audit event creation and verification helpers."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.proposal import AuditEvent
from app.models.user import User

GENESIS_HASH = "0" * 64
AUDIT_LOCK_ID = 62109744


def _event_digest(
    *,
    event_id: str,
    user_id: str | None,
    event_type: str,
    resource_type: str | None,
    resource_id: str | None,
    details: dict[str, Any],
    ip_address: str | None,
    user_agent: str | None,
    created_at: datetime,
    previous_hash: str,
) -> str:
    payload = {
        "id": event_id,
        "user_id": user_id,
        "event_type": event_type,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "details": details,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "created_at": created_at.astimezone(timezone.utc).isoformat(),
        "previous_hash": previous_hash,
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _lock_chain(db: Any) -> None:
    if not isinstance(db, AsyncSession):
        return
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": AUDIT_LOCK_ID},
        )


async def _latest_hash(db: Any) -> str:
    if not isinstance(db, AsyncSession):
        return GENESIS_HASH
    result = await db.execute(
        select(AuditEvent.event_hash)
        .where(AuditEvent.event_hash.isnot(None))
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none() or GENESIS_HASH


async def create_audit_event(
    db: AsyncSession,
    event_type: str,
    user: User | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    *,
    user_id: str | None = None,
) -> AuditEvent:
    await _lock_chain(db)
    previous_hash = await _latest_hash(db)
    event_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc)
    resolved_user_id = user.id if user else user_id
    event_details = details or {}
    event_hash = _event_digest(
        event_id=event_id,
        user_id=resolved_user_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        details=event_details,
        ip_address=ip_address,
        user_agent=user_agent,
        created_at=timestamp,
        previous_hash=previous_hash,
    )
    event = AuditEvent(
        id=event_id,
        user_id=resolved_user_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        details=event_details,
        ip_address=ip_address,
        user_agent=user_agent,
        previous_hash=previous_hash,
        event_hash=event_hash,
        created_at=timestamp,
    )
    db.add(event)
    return event


async def create_durable_audit_event(
    event_type: str,
    user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditEvent:
    """Persist an audit event in its own transaction."""
    from app.database import async_session_factory

    async with async_session_factory() as session:
        event = await create_audit_event(
            session,
            event_type=event_type,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await session.commit()
        return event


def verify_audit_chain(events: list[AuditEvent]) -> dict[str, Any]:
    sealed = [event for event in events if event.event_hash]
    unsealed_count = len(events) - len(sealed)
    previous_hash = GENESIS_HASH
    invalid_event_id: str | None = None
    for event in sealed:
        if event.previous_hash != previous_hash:
            invalid_event_id = event.id
            break
        calculated = _event_digest(
            event_id=event.id,
            user_id=event.user_id,
            event_type=event.event_type,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            details=event.details or {},
            ip_address=event.ip_address,
            user_agent=event.user_agent,
            created_at=event.created_at,
            previous_hash=event.previous_hash or GENESIS_HASH,
        )
        if calculated != event.event_hash:
            invalid_event_id = event.id
            break
        previous_hash = event.event_hash
    return {
        "valid": invalid_event_id is None,
        "sealed_events": len(sealed),
        "legacy_unsealed_events": unsealed_count,
        "invalid_event_id": invalid_event_id,
        "head_hash": previous_hash if sealed else None,
    }
