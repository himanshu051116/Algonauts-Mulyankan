"""Add document roles, gate provenance, and fail-closed scoring invariants.

Revision ID: 20260708_scoring_safety
Revises: 20260706_hardening
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260708_scoring_safety"
down_revision: str | None = "20260706_hardening"
branch_labels = None
depends_on = None

DOCUMENT_ROLES = (
    "main_proposal",
    "budget_annexure",
    "workplan_annexure",
    "pi_cv",
    "team_cv",
    "institution_profile",
    "industry_support_letter",
    "safety_document",
    "environment_document",
    "compliance_document",
    "quotation",
    "previous_project_report",
    "reference_guideline",
    "other",
    "unknown",
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


def upgrade() -> None:
    role_values = _sql_values(DOCUMENT_ROLES)

    op.add_column(
        "upload_sessions",
        sa.Column(
            "document_role",
            sa.String(length=50),
            nullable=False,
            server_default="main_proposal",
        ),
    )
    op.create_check_constraint(
        "ck_upload_session_document_role",
        "upload_sessions",
        f"document_role IN ({role_values})",
    )

    op.add_column(
        "proposal_documents",
        sa.Column(
            "document_role",
            sa.String(length=50),
            nullable=False,
            server_default="main_proposal",
        ),
    )
    op.add_column(
        "proposal_documents",
        sa.Column("classified_role", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "proposal_documents",
        sa.Column(
            "role_status",
            sa.String(length=30),
            nullable=False,
            server_default="legacy_unverified",
        ),
    )
    op.add_column(
        "proposal_documents",
        sa.Column("role_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "proposal_documents",
        sa.Column("role_reason", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_proposal_document_role",
        "proposal_documents",
        f"document_role IN ({role_values})",
    )
    op.create_check_constraint(
        "ck_proposal_document_role_status",
        "proposal_documents",
        "role_status IN ('declared','confirmed','mismatch','uncertain','legacy_unverified')",
    )
    op.create_check_constraint(
        "ck_proposal_document_role_confidence",
        "proposal_documents",
        "role_confidence IS NULL OR (role_confidence >= 0 AND role_confidence <= 1)",
    )
    op.create_index(
        "ix_proposal_documents_role",
        "proposal_documents",
        ["proposal_version_id", "document_role"],
        unique=False,
    )

    op.add_column(
        "model_runs",
        sa.Column("diagnostic_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "model_runs",
        sa.Column(
            "scoring_status",
            sa.String(length=30),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "model_runs",
        sa.Column(
            "gate_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.execute(
        """
        UPDATE model_runs
        SET diagnostic_score = total_score,
            scoring_status = CASE
                WHEN status = 'failed' THEN 'failed'
                WHEN status IN ('queued', 'running') THEN 'pending'
                WHEN status = 'completed' THEN 'legacy_unverified'
                ELSE 'pending'
            END
        """
    )
    op.execute(
        "UPDATE model_runs SET total_score = NULL WHERE scoring_status <> 'released'"
    )
    op.create_check_constraint(
        "ck_model_run_diagnostic_score",
        "model_runs",
        "diagnostic_score IS NULL OR (diagnostic_score >= 0 AND diagnostic_score <= 100)",
    )
    op.create_check_constraint(
        "ck_model_run_scoring_status",
        "model_runs",
        "scoring_status IN ('pending','released','abstained','gate_rejected','manual_review','rules_only','configuration_error','legacy_unverified','failed')",
    )
    op.create_check_constraint(
        "ck_model_run_total_requires_release",
        "model_runs",
        "total_score IS NULL OR scoring_status = 'released'",
    )
    op.create_index(
        "ix_model_runs_scoring_status",
        "model_runs",
        ["scoring_status"],
        unique=False,
    )

    op.add_column(
        "criterion_predictions",
        sa.Column(
            "criterion_status",
            sa.String(length=30),
            nullable=False,
            server_default="unresolved",
        ),
    )
    op.add_column(
        "criterion_predictions",
        sa.Column(
            "released",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "criterion_predictions",
        sa.Column(
            "evidence_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.execute(
        """
        UPDATE criterion_predictions AS prediction
        SET evidence_count = evidence.count
        FROM (
            SELECT criterion_prediction_id, COUNT(*)::integer AS count
            FROM criterion_evidence
            GROUP BY criterion_prediction_id
        ) AS evidence
        WHERE evidence.criterion_prediction_id = prediction.id
        """
    )
    # Historical predictions were produced before evidence contracts existed.
    # Preserve their numeric values as immutable audit history, but mark them
    # unreleased so current APIs cannot present them as verified official scores.
    op.execute(
        """
        UPDATE criterion_predictions
        SET released = false,
            criterion_status = 'legacy_unverified'
        """
    )
    op.create_check_constraint(
        "ck_prediction_criterion_status",
        "criterion_predictions",
        "criterion_status IN ('supported','partially_supported','contradicted','unresolved','not_applicable','extraction_uncertain','role_disallowed','legacy_unverified')",
    )
    op.create_check_constraint(
        "ck_prediction_evidence_count_nonnegative",
        "criterion_predictions",
        "evidence_count >= 0",
    )
    op.create_check_constraint(
        "ck_prediction_score_requires_evidence",
        "criterion_predictions",
        "awarded_score IS NULL OR evidence_count > 0 OR criterion_status = 'legacy_unverified'",
    )
    op.create_check_constraint(
        "ck_prediction_score_requires_release",
        "criterion_predictions",
        "awarded_score IS NULL OR released OR criterion_status = 'legacy_unverified'",
    )
    op.create_check_constraint(
        "ck_prediction_release_requires_score_evidence",
        "criterion_predictions",
        "NOT released OR (awarded_score IS NOT NULL AND evidence_count > 0)",
    )

    op.add_column(
        "criterion_evidence",
        sa.Column("document_role", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "criterion_evidence",
        sa.Column("verification_status", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "criterion_evidence",
        sa.Column("verification_reason", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE criterion_evidence
        SET document_role = 'main_proposal',
            verification_status = COALESCE(assertion_state, 'legacy_candidate')
        """
    )


def downgrade() -> None:
    op.drop_column("criterion_evidence", "verification_reason")
    op.drop_column("criterion_evidence", "verification_status")
    op.drop_column("criterion_evidence", "document_role")

    op.drop_constraint(
        "ck_prediction_release_requires_score_evidence",
        "criterion_predictions",
        type_="check",
    )
    op.drop_constraint(
        "ck_prediction_score_requires_release",
        "criterion_predictions",
        type_="check",
    )
    op.drop_constraint(
        "ck_prediction_score_requires_evidence",
        "criterion_predictions",
        type_="check",
    )
    op.drop_constraint(
        "ck_prediction_evidence_count_nonnegative",
        "criterion_predictions",
        type_="check",
    )
    op.drop_constraint(
        "ck_prediction_criterion_status",
        "criterion_predictions",
        type_="check",
    )
    op.drop_column("criterion_predictions", "evidence_count")
    op.drop_column("criterion_predictions", "released")
    op.drop_column("criterion_predictions", "criterion_status")

    op.drop_index("ix_model_runs_scoring_status", table_name="model_runs")
    op.drop_constraint(
        "ck_model_run_total_requires_release",
        "model_runs",
        type_="check",
    )
    op.execute(
        """
        UPDATE model_runs
        SET total_score = diagnostic_score
        WHERE scoring_status = 'legacy_unverified'
          AND total_score IS NULL
          AND diagnostic_score IS NOT NULL
        """
    )
    op.drop_constraint(
        "ck_model_run_scoring_status",
        "model_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_model_run_diagnostic_score",
        "model_runs",
        type_="check",
    )
    op.drop_column("model_runs", "gate_result")
    op.drop_column("model_runs", "scoring_status")
    op.drop_column("model_runs", "diagnostic_score")

    op.drop_index("ix_proposal_documents_role", table_name="proposal_documents")
    op.drop_constraint(
        "ck_proposal_document_role_confidence",
        "proposal_documents",
        type_="check",
    )
    op.drop_constraint(
        "ck_proposal_document_role_status",
        "proposal_documents",
        type_="check",
    )
    op.drop_constraint(
        "ck_proposal_document_role",
        "proposal_documents",
        type_="check",
    )
    op.drop_column("proposal_documents", "role_reason")
    op.drop_column("proposal_documents", "role_confidence")
    op.drop_column("proposal_documents", "role_status")
    op.drop_column("proposal_documents", "classified_role")
    op.drop_column("proposal_documents", "document_role")

    op.drop_constraint(
        "ck_upload_session_document_role",
        "upload_sessions",
        type_="check",
    )
    op.drop_column("upload_sessions", "document_role")
