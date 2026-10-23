"""Post-freeze provider operation intent; contains no credentials/document contents."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column
from app.base import Base

class RiskopsProviderOperation(Base):
    __tablename__ = 'riskops_provider_operations'
    __table_args__ = (
        CheckConstraint("operation_type IN ('contest_draft', 'evidence_upload')",name='ck_riskops_operation_type'),
        CheckConstraint("status IN ('reserved', 'observed', 'completed', 'ambiguous')",name='ck_riskops_operation_status'),
        Index('ix_riskops_operations_case_created','case_id','created_at'),
        # Database-enforced, race-safe case-wide single-flight gate. A pending or
        # uncertain provider effect blocks ALL new provider mutations on the case.
        Index('uq_riskops_one_pending_per_case','case_id',unique=True,
              postgresql_where=text("status IN ('reserved', 'observed', 'ambiguous')")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    operation_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    case_id: Mapped[str] = mapped_column(ForeignKey('dispute_cases.id',ondelete='CASCADE'), nullable=False)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence_type: Mapped[str | None] = mapped_column(String(40))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    provider_reference: Mapped[str | None] = mapped_column(String(128))
    domain_reference: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
