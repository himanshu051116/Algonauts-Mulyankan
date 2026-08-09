"""Add governed multi-document submission packages.

Revision ID: 20260708_packages
Revises: 20260708_scoring_safety
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260708_packages"
down_revision: str | None = "20260708_scoring_safety"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "proposal_versions",
        sa.Column(
            "package_status",
            sa.String(length=30),
            nullable=False,
            server_default="draft",
        ),
    )
    op.add_column(
        "proposal_versions",
        sa.Column(
            "package_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "proposal_versions",
        sa.Column("package_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "proposal_versions",
        sa.Column("package_policy_version", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "proposal_versions",
        sa.Column("package_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "proposal_versions",
        sa.Column("package_confirmed_by", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_proposal_versions_package_confirmed_by_users",
        "proposal_versions",
        "users",
        ["package_confirmed_by"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_proposal_version_package_status",
        "proposal_versions",
        "package_status IN ('draft','incomplete','ready','confirmed','legacy_single_document')",
    )
    op.create_index(
        "ix_proposal_versions_package_hash",
        "proposal_versions",
        ["package_hash"],
        unique=False,
    )

    op.add_column(
        "upload_sessions",
        sa.Column("requirement_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "proposal_documents",
        sa.Column("requirement_id", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "ix_upload_sessions_requirement",
        "upload_sessions",
        ["proposal_version_id", "requirement_id"],
        unique=False,
    )
    op.create_index(
        "uq_active_document_requirement",
        "proposal_documents",
        ["proposal_version_id", "requirement_id"],
        unique=True,
        postgresql_where=sa.text(
            "requirement_id IS NOT NULL AND superseded_at IS NULL"
        ),
    )

    # Existing evaluated/reviewed proposal versions remain readable as legacy
    # single-document snapshots; this migration never pretends they were
    # applicant-confirmed multi-document packages.
    op.execute(
        """
        UPDATE proposal_versions AS version
        SET package_status = 'legacy_single_document'
        FROM proposals AS proposal
        WHERE proposal.id = version.proposal_id
          AND proposal.status NOT IN ('draft', 'revision_required')
        """
    )


def downgrade() -> None:
    op.drop_index(
        "uq_active_document_requirement", table_name="proposal_documents"
    )
    op.drop_index("ix_upload_sessions_requirement", table_name="upload_sessions")
    op.drop_column("proposal_documents", "requirement_id")
    op.drop_column("upload_sessions", "requirement_id")

    op.drop_index("ix_proposal_versions_package_hash", table_name="proposal_versions")
    op.drop_constraint(
        "ck_proposal_version_package_status",
        "proposal_versions",
        type_="check",
    )
    op.drop_constraint(
        "fk_proposal_versions_package_confirmed_by_users",
        "proposal_versions",
        type_="foreignkey",
    )
    op.drop_column("proposal_versions", "package_confirmed_by")
    op.drop_column("proposal_versions", "package_confirmed_at")
    op.drop_column("proposal_versions", "package_policy_version")
    op.drop_column("proposal_versions", "package_hash")
    op.drop_column("proposal_versions", "package_manifest")
    op.drop_column("proposal_versions", "package_status")
