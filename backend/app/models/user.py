import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.base import Base


class UserRole(str, enum.Enum):
    APPLICANT = "applicant"
    SCRUTINY_OFFICER = "scrutiny_officer"
    TECHNICAL_REVIEWER = "technical_reviewer"
    FINANCIAL_REVIEWER = "financial_reviewer"
    SENIOR_ADJUDICATOR = "senior_adjudicator"
    COMMITTEE_SECRETARIAT = "committee_secretariat"
    ADMINISTRATOR = "administrator"
    AUDITOR = "auditor"
    ML_ENGINEER = "ml_engineer"


def enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False, index=True
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            name="user_role",
            values_callable=enum_values,
            validate_strings=True,
        ),
        default=UserRole.APPLICANT,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    organisation: Mapped[str | None] = mapped_column(String(300), nullable=True)
    expertise: Mapped[str | None] = mapped_column(Text, nullable=True)
    experience_years: Mapped[int | None] = mapped_column(default=0)
    conflict_declarations: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_status: Mapped[str | None] = mapped_column(
        String(30), default="pending", nullable=True
    )
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    proposals = relationship(
        "Proposal", back_populates="owner", foreign_keys="Proposal.owner_id"
    )
    review_assignments = relationship(
        "ReviewerAssignment",
        back_populates="reviewer",
        foreign_keys="ReviewerAssignment.reviewer_id",
    )
    assigned_review_assignments = relationship(
        "ReviewerAssignment",
        back_populates="assigner",
        foreign_keys="ReviewerAssignment.assigned_by",
    )
