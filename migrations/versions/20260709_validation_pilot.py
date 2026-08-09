"""Add expert-grounded validation studies and shadow-pilot records.

Revision ID: 20260709_validation_pilot
Revises: 20260708_packages
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260709_validation_pilot"
down_revision: str | None = "20260708_packages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "validation_studies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scheme_id", sa.String(), nullable=False),
        sa.Column("rubric_version_id", sa.String(), nullable=False),
        sa.Column("model_version_id", sa.String(), nullable=False),
        sa.Column("model_artifact_hash", sa.String(length=64), nullable=False),
        sa.Column("rubric_definition_hash", sa.String(length=64), nullable=False),
        sa.Column("protocol_version", sa.String(length=50), nullable=False),
        sa.Column(
            "annotation_rulebook_version", sa.String(length=50), nullable=False
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "shadow_mode", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "minimum_reviews_per_case",
            sa.Integer(),
            nullable=False,
            server_default="2",
        ),
        sa.Column(
            "recommendation_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft','active','frozen','completed','archived')",
            name="ck_validation_study_status",
        ),
        sa.CheckConstraint(
            "minimum_reviews_per_case >= 2",
            name="ck_validation_study_min_reviews",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["model_version_id"], ["model_versions.id"]),
        sa.ForeignKeyConstraint(["rubric_version_id"], ["rubric_versions.id"]),
        sa.ForeignKeyConstraint(["scheme_id"], ["funding_schemes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_validation_studies_scheme_id",
        "validation_studies",
        ["scheme_id"],
        unique=False,
    )
    op.create_index(
        "ix_validation_studies_status",
        "validation_studies",
        ["status"],
        unique=False,
    )

    op.create_table(
        "validation_cases",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=False),
        sa.Column("proposal_id", sa.String(), nullable=False),
        sa.Column("proposal_version_id", sa.String(), nullable=False),
        sa.Column("model_run_id", sa.String(), nullable=False),
        sa.Column(
            "partition",
            sa.String(length=30),
            nullable=False,
            server_default="shadow",
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("included_by", sa.String(), nullable=False),
        sa.Column(
            "included_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "comparison_ready_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.CheckConstraint(
            "partition IN ('development','internal_test','external_test','shadow')",
            name="ck_validation_case_partition",
        ),
        sa.CheckConstraint(
            "status IN ('queued','under_review','ready','compared','excluded')",
            name="ck_validation_case_status",
        ),
        sa.ForeignKeyConstraint(["included_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["model_run_id"], ["model_runs.id"]),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"]),
        sa.ForeignKeyConstraint(
            ["proposal_version_id"], ["proposal_versions.id"]
        ),
        sa.ForeignKeyConstraint(["study_id"], ["validation_studies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "study_id", "proposal_id", name="uq_validation_case_study_proposal"
        ),
        sa.UniqueConstraint(
            "study_id",
            "proposal_version_id",
            name="uq_validation_case_study_version",
        ),
    )
    op.create_index(
        "ix_validation_cases_study_id",
        "validation_cases",
        ["study_id"],
        unique=False,
    )
    op.create_index(
        "ix_validation_cases_proposal_id",
        "validation_cases",
        ["proposal_id"],
        unique=False,
    )
    op.create_index(
        "ix_validation_cases_proposal_version_id",
        "validation_cases",
        ["proposal_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_validation_cases_status",
        "validation_cases",
        ["status"],
        unique=False,
    )

    op.create_table(
        "validation_consensus",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("validation_case_id", sa.String(), nullable=False),
        sa.Column("expert_total_score", sa.Float(), nullable=False),
        sa.Column("expert_recommendation", sa.String(length=30), nullable=True),
        sa.Column("reviewer_count", sa.Integer(), nullable=False),
        sa.Column(
            "consensus_method",
            sa.String(length=50),
            nullable=False,
            server_default="mean_of_blind_reviews",
        ),
        sa.Column(
            "criterion_scores",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "agreement_metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "expert_total_score >= 0 AND expert_total_score <= 100",
            name="ck_validation_consensus_score",
        ),
        sa.CheckConstraint(
            "reviewer_count >= 2", name="ck_validation_consensus_reviewers"
        ),
        sa.ForeignKeyConstraint(
            ["validation_case_id"], ["validation_cases.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "validation_case_id", name="uq_validation_consensus_case"
        ),
    )

    op.create_table(
        "shadow_comparisons",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("validation_case_id", sa.String(), nullable=False),
        sa.Column("model_total_score", sa.Float(), nullable=True),
        sa.Column("expert_total_score", sa.Float(), nullable=False),
        sa.Column("score_error", sa.Float(), nullable=True),
        sa.Column("absolute_error", sa.Float(), nullable=True),
        sa.Column("squared_error", sa.Float(), nullable=True),
        sa.Column("model_scoring_status", sa.String(length=30), nullable=False),
        sa.Column("model_released", sa.Boolean(), nullable=False),
        sa.Column("model_recommendation", sa.String(length=30), nullable=True),
        sa.Column("expert_recommendation", sa.String(length=30), nullable=True),
        sa.Column("recommendation_agreement", sa.Boolean(), nullable=True),
        sa.Column("model_confidence", sa.Float(), nullable=True),
        sa.Column("model_information_sufficiency", sa.Float(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "model_total_score IS NULL OR (model_total_score >= 0 AND model_total_score <= 100)",
            name="ck_shadow_comparison_model_score",
        ),
        sa.CheckConstraint(
            "expert_total_score >= 0 AND expert_total_score <= 100",
            name="ck_shadow_comparison_expert_score",
        ),
        sa.ForeignKeyConstraint(
            ["validation_case_id"], ["validation_cases.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "validation_case_id", name="uq_shadow_comparison_case"
        ),
    )

    op.create_table(
        "validation_metric_snapshots",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=False),
        sa.Column("snapshot_group_id", sa.String(length=64), nullable=False),
        sa.Column(
            "partition",
            sa.String(length=30),
            nullable=False,
            server_default="all",
        ),
        sa.Column("metric_name", sa.String(length=120), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "partition IN ('all','development','internal_test','external_test','shadow')",
            name="ck_validation_metric_partition",
        ),
        sa.CheckConstraint(
            "sample_size >= 0", name="ck_validation_metric_sample_size"
        ),
        sa.ForeignKeyConstraint(["study_id"], ["validation_studies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_validation_metric_snapshots_study_id",
        "validation_metric_snapshots",
        ["study_id"],
        unique=False,
    )
    op.create_index(
        "ix_validation_metric_snapshots_group",
        "validation_metric_snapshots",
        ["snapshot_group_id"],
        unique=False,
    )

    op.add_column(
        "reviewer_assignments",
        sa.Column("validation_case_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_reviewer_assignments_validation_case",
        "reviewer_assignments",
        "validation_cases",
        ["validation_case_id"],
        ["id"],
    )
    op.create_index(
        "ix_reviewer_assignments_validation_case_id",
        "reviewer_assignments",
        ["validation_case_id"],
        unique=False,
    )

    op.add_column(
        "expert_reviews",
        sa.Column("annotation_protocol_version", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "expert_reviews",
        sa.Column("annotation_rulebook_version", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "expert_reviews",
        sa.Column(
            "model_output_visible_at_submission",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("expert_reviews", "model_output_visible_at_submission")
    op.drop_column("expert_reviews", "annotation_rulebook_version")
    op.drop_column("expert_reviews", "annotation_protocol_version")

    op.drop_index(
        "ix_reviewer_assignments_validation_case_id",
        table_name="reviewer_assignments",
    )
    op.drop_constraint(
        "fk_reviewer_assignments_validation_case",
        "reviewer_assignments",
        type_="foreignkey",
    )
    op.drop_column("reviewer_assignments", "validation_case_id")

    op.drop_index(
        "ix_validation_metric_snapshots_group",
        table_name="validation_metric_snapshots",
    )
    op.drop_index(
        "ix_validation_metric_snapshots_study_id",
        table_name="validation_metric_snapshots",
    )
    op.drop_table("validation_metric_snapshots")
    op.drop_table("shadow_comparisons")
    op.drop_table("validation_consensus")

    op.drop_index("ix_validation_cases_status", table_name="validation_cases")
    op.drop_index(
        "ix_validation_cases_proposal_version_id", table_name="validation_cases"
    )
    op.drop_index(
        "ix_validation_cases_proposal_id", table_name="validation_cases"
    )
    op.drop_index("ix_validation_cases_study_id", table_name="validation_cases")
    op.drop_table("validation_cases")

    op.drop_index("ix_validation_studies_status", table_name="validation_studies")
    op.drop_index(
        "ix_validation_studies_scheme_id", table_name="validation_studies"
    )
    op.drop_table("validation_studies")
