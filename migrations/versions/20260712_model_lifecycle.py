"""Add evidence-backed model lifecycle and quality-report identity.

Revision ID: 20260712_model_lifecycle
Revises: 20260709_validation_pilot
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "20260712_model_lifecycle"
down_revision: str | None = "20260709_validation_pilot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_versions",
        sa.Column(
            "lifecycle_state",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'bootstrap'"),
        ),
    )
    op.add_column(
        "model_versions",
        sa.Column("quality_gate_report_hash", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_model_version_lifecycle_state",
        "model_versions",
        "lifecycle_state IN ('bootstrap', 'candidate', 'shadow', "
        "'externally_tested', 'institutionally_accepted', 'retired')",
    )
    op.create_check_constraint(
        "ck_model_version_quality_report_hash",
        "model_versions",
        "quality_gate_report_hash IS NULL OR length(quality_gate_report_hash) = 64",
    )
    op.create_check_constraint(
        "ck_model_version_promotion_evidence",
        "model_versions",
        "lifecycle_state IN ('bootstrap', 'retired') "
        "OR quality_gate_report_hash IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_model_version_promotion_evidence",
        "model_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_model_version_quality_report_hash",
        "model_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_model_version_lifecycle_state",
        "model_versions",
        type_="check",
    )
    op.drop_column("model_versions", "quality_gate_report_hash")
    op.drop_column("model_versions", "lifecycle_state")
