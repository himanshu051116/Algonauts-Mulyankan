"""Harden version snapshots, document authority, workflow constraints, and audit immutability.

Revision ID: 20260706_hardening
Revises: 20260705_integrity
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260706_hardening"
down_revision: str | None = "20260705_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Preserve the exact title that belonged to each submitted/reviewed version.
    op.add_column(
        "proposal_versions",
        sa.Column("title", sa.String(length=500), nullable=True),
    )
    op.execute(
        """
        UPDATE proposal_versions AS pv
        SET title = p.title
        FROM proposals AS p
        WHERE p.id = pv.proposal_id AND pv.title IS NULL
        """
    )
    op.alter_column("proposal_versions", "title", nullable=False)

    # Make the multi-upload policy explicit: previous uploads are retained but
    # exactly one non-superseded document is authoritative for a version.
    op.add_column(
        "proposal_documents",
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "proposal_documents",
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY proposal_version_id
                       ORDER BY upload_completed_at DESC NULLS LAST, created_at DESC, id DESC
                   ) AS position
            FROM proposal_documents
        )
        UPDATE proposal_documents AS d
        SET is_primary = (ranked.position = 1),
            superseded_at = CASE
                WHEN ranked.position = 1 THEN NULL
                ELSE COALESCE(d.upload_completed_at, d.created_at, CURRENT_TIMESTAMP)
            END
        FROM ranked
        WHERE ranked.id = d.id
        """
    )
    op.create_index(
        "uq_primary_document_per_proposal_version",
        "proposal_documents",
        ["proposal_version_id"],
        unique=True,
        postgresql_where=sa.text("is_primary AND superseded_at IS NULL"),
    )
    op.alter_column(
        "proposal_documents", "is_primary", server_default=sa.true()
    )

    op.create_check_constraint(
        "ck_proposal_status_valid",
        "proposals",
        "status IN ('draft','revision_required','submitted','evaluating','human_review',"
        "'adjudication','committee_review','approved','rejected','withdrawn','error')",
    )
    op.create_check_constraint(
        "ck_proposal_document_file_size_positive",
        "proposal_documents",
        "file_size > 0",
    )
    op.create_check_constraint(
        "ck_upload_session_status_valid",
        "upload_sessions",
        "status IN ('pending','consumed','failed','expired')",
    )
    op.create_check_constraint(
        "ck_upload_session_maximum_size_positive",
        "upload_sessions",
        "maximum_size > 0",
    )
    op.create_check_constraint(
        "ck_upload_session_expected_size_positive",
        "upload_sessions",
        "expected_size IS NULL OR expected_size > 0",
    )
    op.create_check_constraint(
        "ck_model_run_status_valid",
        "model_runs",
        "status IN ('queued','running','completed','failed')",
    )
    op.create_check_constraint(
        "ck_assignment_role_valid",
        "reviewer_assignments",
        "role IN ('technical','financial')",
    )
    op.create_check_constraint(
        "ck_assignment_status_valid",
        "reviewer_assignments",
        "status IN ('pending','accepted','in_progress','conflict_declared','completed','cancelled')",
    )
    op.create_check_constraint(
        "ck_expert_review_total_score",
        "expert_reviews",
        "total_score IS NULL OR (total_score >= 0 AND total_score <= 100)",
    )
    op.create_check_constraint(
        "ck_expert_review_recommendation_valid",
        "expert_reviews",
        "recommendation IS NULL OR recommendation IN ('approved','revision','rejected')",
    )
    op.create_check_constraint(
        "ck_committee_decision_valid",
        "committee_decisions",
        "decision IN ('approved','rejected','revision_required')",
    )
    op.create_check_constraint(
        "ck_committee_model_score",
        "committee_decisions",
        "model_score_at_decision IS NULL OR (model_score_at_decision >= 0 AND model_score_at_decision <= 100)",
    )
    op.create_check_constraint(
        "ck_committee_expert_score",
        "committee_decisions",
        "expert_score_at_decision IS NULL OR (expert_score_at_decision >= 0 AND expert_score_at_decision <= 100)",
    )

    # PostgreSQL audit rows become append-only. The application hash chain
    # detects tampering; this trigger also prevents ordinary UPDATE/DELETE.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_audit_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_event_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_event_mutation()")

    for constraint, table in (
        ("ck_committee_expert_score", "committee_decisions"),
        ("ck_committee_model_score", "committee_decisions"),
        ("ck_committee_decision_valid", "committee_decisions"),
        ("ck_expert_review_recommendation_valid", "expert_reviews"),
        ("ck_expert_review_total_score", "expert_reviews"),
        ("ck_assignment_status_valid", "reviewer_assignments"),
        ("ck_assignment_role_valid", "reviewer_assignments"),
        ("ck_model_run_status_valid", "model_runs"),
        ("ck_upload_session_expected_size_positive", "upload_sessions"),
        ("ck_upload_session_maximum_size_positive", "upload_sessions"),
        ("ck_upload_session_status_valid", "upload_sessions"),
        ("ck_proposal_document_file_size_positive", "proposal_documents"),
        ("ck_proposal_status_valid", "proposals"),
    ):
        op.drop_constraint(constraint, table, type_="check")

    op.drop_index(
        "uq_primary_document_per_proposal_version",
        table_name="proposal_documents",
    )
    op.drop_column("proposal_documents", "superseded_at")
    op.drop_column("proposal_documents", "is_primary")
    op.drop_column("proposal_versions", "title")
