"""Durable fail-closed intent journal for non-idempotent Razorpay actions.

Operations are RESERVED in a separate committed DB transaction *before* the
provider call. A duplicate or unknown previous outcome NEVER triggers a retry.
There is no claim of exactly-once delivery or provider reconciliation.
"""
from __future__ import annotations

import hashlib
import uuid
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import async_session_factory
from app.models.riskops_operation import RiskopsProviderOperation


class OperationAlreadyExists(RuntimeError):
    """An earlier attempt is persisted; explicit reconciliation is required."""


def operation_key(case_id: str, operation_type: str, evidence_type: str = '', content_sha256: str = '') -> str:
    if operation_type not in ('contest_draft','evidence_upload'):
        raise ValueError('unapproved provider operation')
    if operation_type == 'evidence_upload' and (not evidence_type or len(content_sha256) != 64):
        raise ValueError('evidence operation requires evidence type and SHA-256')
    # The draft is *one attempt per case*, regardless of summary/amount changes.
    raw = '\x00'.join(('riskops-v7', str(case_id), operation_type, evidence_type, content_sha256))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


class OperationJournal:
    def __init__(self, factory=async_session_factory):
        self.factory = factory

    async def reserve(self, *, case_id: str, owner_id: str, operation_type: str,
                      evidence_type: str = '', content_sha256: str = '') -> str:
        key = operation_key(case_id,operation_type,evidence_type,content_sha256)
        op_id = str(uuid.uuid4())
        async with self.factory() as session:
            # Database unique keys jointly protect exact-attempt replay and the
            # single-flight case lane, even across independent workers.
            # A pending/uncertain earlier action must block a new payload hash
            # or a contest draft for this case, too.
            stmt = insert(RiskopsProviderOperation).values(
                id=op_id,operation_key=key,case_id=case_id,owner_id=owner_id,
                operation_type=operation_type,status='reserved',
                evidence_type=evidence_type or None,content_sha256=content_sha256 or None,
            ).on_conflict_do_nothing().returning(RiskopsProviderOperation.id)
            result=await session.execute(stmt)
            acquired=result.scalar_one_or_none()
            await session.commit()  # MUST be durably committed before provider call.
            if not acquired:
                raise OperationAlreadyExists('A previous attempt or unresolved case operation exists; reconcile before retrying')
        return op_id

    async def transition(self, *, operation_id: str, owner_id: str, state: str,
                         provider_reference: str | None = None, domain_reference: str | None = None,
                         error_code: str | None = None) -> bool:
        # Only forward, never reset a confirmed/ambiguous action to an untried state.
        allowed_previous={'observed':['reserved'], 'completed':['observed'], 'ambiguous':['reserved','observed']}
        if state not in allowed_previous:
            raise ValueError('Invalid journal state')
        values={'status':state}
        if provider_reference is not None:
            values['provider_reference']=str(provider_reference)[:128]
        if domain_reference is not None:
            values['domain_reference']=str(domain_reference)[:64]
        if error_code is not None:
            values['error_code']=str(error_code)[:40]
        async with self.factory() as session:
            result=await session.execute(update(RiskopsProviderOperation).where(
                RiskopsProviderOperation.id == operation_id,
                RiskopsProviderOperation.owner_id == owner_id,
                RiskopsProviderOperation.status.in_(allowed_previous[state]),
            ).values(**values).returning(RiskopsProviderOperation.id))
            matched=result.scalar_one_or_none() is not None
            await session.commit()
            return matched

    async def for_case(self, *, case_id: str, owner_id: str) -> list[dict]:
        async with self.factory() as session:
            result=await session.execute(select(RiskopsProviderOperation).where(
                RiskopsProviderOperation.case_id == case_id,
                RiskopsProviderOperation.owner_id == owner_id,
            ).order_by(RiskopsProviderOperation.created_at.desc()).limit(100))
            return [dict(id=row.id,operation_type=row.operation_type,status=row.status,
                         evidence_type=row.evidence_type,provider_reference=row.provider_reference,
                         domain_reference=row.domain_reference,error_code=row.error_code,
                         created_at=row.created_at,
                         reconciliation_required=row.status != 'completed') for row in result.scalars()]
