"""Add semantic coverage and canonical field metadata columns.

Revision ID: 20260704_semantic_fields
Revises: 20260704_eval_runs
Create Date: 2026-07-04 00:00:00.000000

Existing confidence columns are retained for backward compatibility. New
writes should use evidence_coverage, information_sufficiency, or
extraction_completeness according to the deterministic workflow semantics.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260704_semantic_fields"
down_revision = "20260704_eval_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("document_pages", sa.Column("extraction_completeness", sa.Float(), nullable=True))
    op.add_column("proposal_sections", sa.Column("evidence_coverage", sa.Float(), nullable=True))
    op.add_column("extracted_fields", sa.Column("normalized_value", sa.Text(), nullable=True))
    op.add_column("extracted_fields", sa.Column("original_text", sa.Text(), nullable=True))
    op.add_column("extracted_fields", sa.Column("evidence_coverage", sa.Float(), nullable=True))
    op.add_column(
        "extracted_fields",
        sa.Column("validation_warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("extracted_fields", sa.Column("manually_corrected_value", sa.Text(), nullable=True))
    op.add_column("extracted_fields", sa.Column("corrected_by", sa.String(), nullable=True))
    op.add_column("extracted_fields", sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_extracted_fields_corrected_by_users",
        "extracted_fields",
        "users",
        ["corrected_by"],
        ["id"],
    )
    op.add_column("model_runs", sa.Column("information_sufficiency", sa.Float(), nullable=True))
    op.add_column("rule_results", sa.Column("evidence_coverage", sa.Float(), nullable=True))
    op.add_column("criterion_predictions", sa.Column("information_sufficiency", sa.Float(), nullable=True))
    op.add_column("expert_criterion_scores", sa.Column("evidence_coverage", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("expert_criterion_scores", "evidence_coverage")
    op.drop_column("criterion_predictions", "information_sufficiency")
    op.drop_column("rule_results", "evidence_coverage")
    op.drop_column("model_runs", "information_sufficiency")
    op.drop_constraint("fk_extracted_fields_corrected_by_users", "extracted_fields", type_="foreignkey")
    op.drop_column("extracted_fields", "corrected_at")
    op.drop_column("extracted_fields", "corrected_by")
    op.drop_column("extracted_fields", "manually_corrected_value")
    op.drop_column("extracted_fields", "validation_warnings")
    op.drop_column("extracted_fields", "evidence_coverage")
    op.drop_column("extracted_fields", "original_text")
    op.drop_column("extracted_fields", "normalized_value")
    op.drop_column("proposal_sections", "evidence_coverage")
    op.drop_column("document_pages", "extraction_completeness")
