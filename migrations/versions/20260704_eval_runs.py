"""Persist full evaluation runs, rule results, and rubric predictions.

Revision ID: 20260704_eval_runs
Revises: 20260704_upload_sessions
Create Date: 2026-07-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260704_eval_runs"
down_revision = "20260704_upload_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("rubric_criteria", sa.Column("criterion_key", sa.String(length=100), nullable=True))

    op.add_column("model_runs", sa.Column("engine_version", sa.String(length=50), nullable=True))
    op.add_column("model_runs", sa.Column("trigger_user_id", sa.String(), nullable=True))
    op.add_column("model_runs", sa.Column("rerun_reason", sa.Text(), nullable=True))
    op.add_column("model_runs", sa.Column("input_checksum", sa.String(length=64), nullable=True))
    op.add_column("model_runs", sa.Column("output_checksum", sa.String(length=64), nullable=True))
    op.add_column(
        "model_runs",
        sa.Column(
            "evaluation_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column("model_runs", sa.Column("failure_code", sa.String(length=50), nullable=True))
    op.add_column(
        "model_runs",
        sa.Column(
            "failure_details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_model_runs_trigger_user_id_users",
        "model_runs",
        "users",
        ["trigger_user_id"],
        ["id"],
    )

    op.add_column("rule_results", sa.Column("rule_identifier", sa.String(length=100), nullable=True))
    op.add_column("rule_results", sa.Column("rule_version", sa.String(length=20), nullable=True))
    op.add_column(
        "rule_results",
        sa.Column(
            "input_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column("rule_results", sa.Column("explanation", sa.Text(), nullable=True))
    op.add_column("rule_results", sa.Column("evidence_excerpt", sa.Text(), nullable=True))
    op.add_column("rule_results", sa.Column("page_reference", sa.String(length=50), nullable=True))
    op.add_column("rule_results", sa.Column("section_reference", sa.String(length=50), nullable=True))
    op.add_column(
        "rule_results",
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    op.add_column("criterion_predictions", sa.Column("category_score", sa.Float(), nullable=True))
    op.add_column("criterion_predictions", sa.Column("evidence_coverage", sa.Float(), nullable=True))
    op.add_column(
        "criterion_predictions",
        sa.Column(
            "missing_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column("criterion_predictions", sa.Column("abstention", sa.Boolean(), nullable=True))
    op.add_column(
        "criterion_predictions",
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("criterion_predictions", "warnings")
    op.drop_column("criterion_predictions", "abstention")
    op.drop_column("criterion_predictions", "missing_evidence")
    op.drop_column("criterion_predictions", "evidence_coverage")
    op.drop_column("criterion_predictions", "category_score")

    op.drop_column("rule_results", "warnings")
    op.drop_column("rule_results", "section_reference")
    op.drop_column("rule_results", "page_reference")
    op.drop_column("rule_results", "evidence_excerpt")
    op.drop_column("rule_results", "explanation")
    op.drop_column("rule_results", "input_payload")
    op.drop_column("rule_results", "rule_version")
    op.drop_column("rule_results", "rule_identifier")

    op.drop_constraint("fk_model_runs_trigger_user_id_users", "model_runs", type_="foreignkey")
    op.drop_column("model_runs", "failure_details")
    op.drop_column("model_runs", "failure_code")
    op.drop_column("model_runs", "evaluation_payload")
    op.drop_column("model_runs", "output_checksum")
    op.drop_column("model_runs", "input_checksum")
    op.drop_column("model_runs", "rerun_reason")
    op.drop_column("model_runs", "trigger_user_id")
    op.drop_column("model_runs", "engine_version")

    op.drop_column("rubric_criteria", "criterion_key")
