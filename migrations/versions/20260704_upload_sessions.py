"""Add upload sessions

Revision ID: 20260704_upload_sessions
Revises: 609a290ee409
Create Date: 2026-07-04 04:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260704_upload_sessions"
down_revision: str | None = "609a290ee409"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_id", sa.String(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("proposal_id", sa.String(), sa.ForeignKey("proposals.id"), nullable=False, index=True),
        sa.Column("proposal_version_id", sa.String(), sa.ForeignKey("proposal_versions.id"), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False, unique=True),
        sa.Column("storage_path", sa.String(500), nullable=False, unique=True),
        sa.Column("expected_file_name", sa.String(300), nullable=False),
        sa.Column("allowed_content_types", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("maximum_size", sa.Integer(), nullable=False),
        sa.Column("expected_size", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("upload_sessions")
