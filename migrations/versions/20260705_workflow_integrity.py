"""Add proposal version metadata and database integrity constraints.

Revision ID: 20260705_integrity
Revises: 20260704_semantic_fields
Create Date: 2026-07-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260705_integrity"
down_revision: str | None = "20260704_semantic_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "proposal_versions", sa.Column("executive_summary", sa.Text(), nullable=True)
    )
    op.add_column(
        "audit_events", sa.Column("previous_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "audit_events", sa.Column("event_hash", sa.String(length=64), nullable=True)
    )
    op.create_index(
        "ux_audit_events_event_hash", "audit_events", ["event_hash"], unique=True
    )
    op.add_column(
        "reviewer_assignments",
        sa.Column("proposal_version_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_assignment_proposal_version",
        "reviewer_assignments",
        "proposal_versions",
        ["proposal_version_id"],
        ["id"],
    )
    op.execute(
        sa.text(
            """
            UPDATE reviewer_assignments AS assignment
            SET proposal_version_id = version.id
            FROM proposals AS proposal
            JOIN proposal_versions AS version
              ON version.proposal_id = proposal.id
             AND version.version_number = proposal.current_version
            WHERE assignment.proposal_id = proposal.id
              AND assignment.proposal_version_id IS NULL
            """
        )
    )
    op.alter_column(
        "reviewer_assignments",
        "proposal_version_id",
        existing_type=sa.String(),
        nullable=False,
    )

    for table_name in ("adjudications", "committee_decisions"):
        op.add_column(
            table_name,
            sa.Column("proposal_version_id", sa.String(), nullable=True),
        )
        op.create_foreign_key(
            f"fk_{table_name}_proposal_version",
            table_name,
            "proposal_versions",
            ["proposal_version_id"],
            ["id"],
        )
        op.execute(
            sa.text(
                f"""
                UPDATE {table_name} AS record
                SET proposal_version_id = version.id
                FROM proposals AS proposal
                JOIN proposal_versions AS version
                  ON version.proposal_id = proposal.id
                 AND version.version_number = proposal.current_version
                WHERE record.proposal_id = proposal.id
                  AND record.proposal_version_id IS NULL
                """
            )
        )
        op.alter_column(
            table_name,
            "proposal_version_id",
            existing_type=sa.String(),
            nullable=False,
        )

    op.drop_constraint(
        "committee_decisions_proposal_id_key",
        "committee_decisions",
        type_="unique",
    )

    # Existing duplicate data must be resolved explicitly rather than silently deleted.

    op.create_unique_constraint(
        "uq_guideline_scheme_version", "guideline_versions", ["scheme_id", "version"]
    )
    op.create_unique_constraint(
        "uq_rubric_scheme_version", "rubric_versions", ["scheme_id", "version"]
    )
    op.create_unique_constraint(
        "uq_rubric_criterion_key",
        "rubric_criteria",
        ["rubric_version_id", "criterion_key"],
    )
    op.create_unique_constraint(
        "uq_proposal_version_number",
        "proposal_versions",
        ["proposal_id", "version_number"],
    )
    op.create_unique_constraint(
        "uq_document_page_number", "document_pages", ["document_id", "page_number"]
    )
    op.create_unique_constraint(
        "uq_extracted_field_document_name",
        "extracted_fields",
        ["document_id", "field_name"],
    )
    op.create_unique_constraint(
        "uq_model_name_version", "model_versions", ["model_name", "version"]
    )
    op.create_index(
        "uq_active_rubric_per_scheme",
        "rubric_versions",
        ["scheme_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "uq_active_model_per_rubric",
        "model_versions",
        ["rubric_version_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_unique_constraint(
        "uq_rule_result_run_definition",
        "rule_results",
        ["model_run_id", "rule_definition_id"],
    )
    op.create_unique_constraint(
        "uq_prediction_run_criterion",
        "criterion_predictions",
        ["model_run_id", "rubric_criterion_id"],
    )
    op.create_unique_constraint(
        "uq_similarity_run_version",
        "similarity_matches",
        ["model_run_id", "matched_proposal_version_id"],
    )
    op.create_unique_constraint(
        "uq_assignment_version_reviewer",
        "reviewer_assignments",
        ["proposal_version_id", "reviewer_id"],
    )
    op.create_unique_constraint(
        "uq_expert_score_review_criterion",
        "expert_criterion_scores",
        ["review_id", "rubric_criterion_id"],
    )
    op.create_unique_constraint(
        "uq_monitoring_run_metric",
        "model_monitoring_metrics",
        ["model_run_id", "metric_name"],
    )
    op.create_unique_constraint(
        "uq_committee_decision_proposal_version",
        "committee_decisions",
        ["proposal_version_id"],
    )

    op.create_check_constraint(
        "ck_rubric_total_marks_positive", "rubric_versions", "total_marks > 0"
    )
    op.create_check_constraint(
        "ck_rubric_criterion_maximum_nonnegative", "rubric_criteria", "maximum >= 0"
    )
    op.create_check_constraint(
        "ck_rubric_criterion_weight_nonnegative", "rubric_criteria", "weight >= 0"
    )
    op.create_check_constraint(
        "ck_proposal_current_version_positive", "proposals", "current_version >= 1"
    )
    op.create_check_constraint(
        "ck_proposal_version_number_positive",
        "proposal_versions",
        "version_number >= 1",
    )
    op.create_check_constraint(
        "ck_document_page_number_positive", "document_pages", "page_number >= 1"
    )
    op.create_check_constraint(
        "ck_document_page_word_count_nonnegative", "document_pages", "word_count >= 0"
    )
    op.create_check_constraint(
        "ck_document_page_ocr_confidence",
        "document_pages",
        "ocr_confidence IS NULL OR (ocr_confidence >= 0 AND ocr_confidence <= 1)",
    )
    op.create_check_constraint(
        "ck_document_page_completeness",
        "document_pages",
        "extraction_completeness IS NULL OR (extraction_completeness >= 0 AND extraction_completeness <= 1)",
    )
    op.create_check_constraint(
        "ck_extracted_field_confidence",
        "extracted_fields",
        "extraction_confidence IS NULL OR (extraction_confidence >= 0 AND extraction_confidence <= 1)",
    )
    op.create_check_constraint(
        "ck_extracted_field_coverage",
        "extracted_fields",
        "evidence_coverage IS NULL OR (evidence_coverage >= 0 AND evidence_coverage <= 1)",
    )
    op.create_check_constraint(
        "ck_model_training_rows_nonnegative", "model_versions", "training_rows >= 0"
    )
    op.create_check_constraint(
        "ck_model_run_total_score",
        "model_runs",
        "total_score IS NULL OR (total_score >= 0 AND total_score <= 100)",
    )
    op.create_check_constraint(
        "ck_model_run_confidence",
        "model_runs",
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
    )
    op.create_check_constraint(
        "ck_model_run_information_sufficiency",
        "model_runs",
        "information_sufficiency IS NULL OR (information_sufficiency >= 0 AND information_sufficiency <= 1)",
    )
    op.create_check_constraint(
        "ck_rule_result_confidence",
        "rule_results",
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
    )
    op.create_check_constraint(
        "ck_rule_result_coverage",
        "rule_results",
        "evidence_coverage IS NULL OR (evidence_coverage >= 0 AND evidence_coverage <= 1)",
    )
    op.create_check_constraint(
        "ck_prediction_maximum_nonnegative",
        "criterion_predictions",
        "maximum_score >= 0",
    )
    op.create_check_constraint(
        "ck_prediction_awarded_score",
        "criterion_predictions",
        "awarded_score IS NULL OR (awarded_score >= 0 AND awarded_score <= maximum_score)",
    )
    op.create_check_constraint(
        "ck_prediction_confidence",
        "criterion_predictions",
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
    )
    op.create_check_constraint(
        "ck_prediction_coverage",
        "criterion_predictions",
        "evidence_coverage IS NULL OR (evidence_coverage >= 0 AND evidence_coverage <= 1)",
    )
    op.create_check_constraint(
        "ck_prediction_sufficiency",
        "criterion_predictions",
        "information_sufficiency IS NULL OR (information_sufficiency >= 0 AND information_sufficiency <= 1)",
    )
    op.create_check_constraint(
        "ck_similarity_score",
        "similarity_matches",
        "similarity_score >= 0 AND similarity_score <= 1",
    )
    op.create_check_constraint(
        "ck_expert_score_nonnegative", "expert_criterion_scores", "score >= 0"
    )
    op.create_check_constraint(
        "ck_expert_score_confidence",
        "expert_criterion_scores",
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
    )
    op.create_check_constraint(
        "ck_expert_score_coverage",
        "expert_criterion_scores",
        "evidence_coverage IS NULL OR (evidence_coverage >= 0 AND evidence_coverage <= 1)",
    )
    op.create_check_constraint(
        "ck_adjudication_score",
        "adjudications",
        "resolved_score IS NULL OR (resolved_score >= 0 AND resolved_score <= 100)",
    )

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION prevent_append_only_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'append-only records cannot be updated or deleted';
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    for table_name in ("audit_events", "security_events"):
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {table_name}_append_only
                BEFORE UPDATE OR DELETE ON {table_name}
                FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation()
                """
            )
        )


def downgrade() -> None:
    op.drop_index("uq_active_model_per_rubric", table_name="model_versions")
    op.drop_index("uq_active_rubric_per_scheme", table_name="rubric_versions")
    for table_name in ("security_events", "audit_events"):
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {table_name}_append_only ON {table_name}"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS prevent_append_only_mutation"))
    op.drop_index("ux_audit_events_event_hash", table_name="audit_events")
    op.drop_column("audit_events", "event_hash")
    op.drop_column("audit_events", "previous_hash")
    for table, name in [
        ("adjudications", "ck_adjudication_score"),
        ("expert_criterion_scores", "ck_expert_score_coverage"),
        ("expert_criterion_scores", "ck_expert_score_confidence"),
        ("expert_criterion_scores", "ck_expert_score_nonnegative"),
        ("similarity_matches", "ck_similarity_score"),
        ("criterion_predictions", "ck_prediction_sufficiency"),
        ("criterion_predictions", "ck_prediction_coverage"),
        ("criterion_predictions", "ck_prediction_confidence"),
        ("criterion_predictions", "ck_prediction_awarded_score"),
        ("criterion_predictions", "ck_prediction_maximum_nonnegative"),
        ("rule_results", "ck_rule_result_coverage"),
        ("rule_results", "ck_rule_result_confidence"),
        ("model_runs", "ck_model_run_information_sufficiency"),
        ("model_runs", "ck_model_run_confidence"),
        ("model_runs", "ck_model_run_total_score"),
        ("model_versions", "ck_model_training_rows_nonnegative"),
        ("extracted_fields", "ck_extracted_field_coverage"),
        ("extracted_fields", "ck_extracted_field_confidence"),
        ("document_pages", "ck_document_page_completeness"),
        ("document_pages", "ck_document_page_ocr_confidence"),
        ("document_pages", "ck_document_page_word_count_nonnegative"),
        ("document_pages", "ck_document_page_number_positive"),
        ("proposal_versions", "ck_proposal_version_number_positive"),
        ("proposals", "ck_proposal_current_version_positive"),
        ("rubric_criteria", "ck_rubric_criterion_weight_nonnegative"),
        ("rubric_criteria", "ck_rubric_criterion_maximum_nonnegative"),
        ("rubric_versions", "ck_rubric_total_marks_positive"),
    ]:
        op.drop_constraint(name, table, type_="check")

    for table, name in [
        ("committee_decisions", "uq_committee_decision_proposal_version"),
        ("model_monitoring_metrics", "uq_monitoring_run_metric"),
        ("expert_criterion_scores", "uq_expert_score_review_criterion"),
        ("reviewer_assignments", "uq_assignment_version_reviewer"),
        ("similarity_matches", "uq_similarity_run_version"),
        ("criterion_predictions", "uq_prediction_run_criterion"),
        ("rule_results", "uq_rule_result_run_definition"),
        ("model_versions", "uq_model_name_version"),
        ("extracted_fields", "uq_extracted_field_document_name"),
        ("document_pages", "uq_document_page_number"),
        ("proposal_versions", "uq_proposal_version_number"),
        ("rubric_criteria", "uq_rubric_criterion_key"),
        ("rubric_versions", "uq_rubric_scheme_version"),
        ("guideline_versions", "uq_guideline_scheme_version"),
    ]:
        op.drop_constraint(name, table, type_="unique")

    op.create_unique_constraint(
        "committee_decisions_proposal_id_key",
        "committee_decisions",
        ["proposal_id"],
    )
    for table_name in ("committee_decisions", "adjudications"):
        op.drop_constraint(
            f"fk_{table_name}_proposal_version",
            table_name,
            type_="foreignkey",
        )
        op.drop_column(table_name, "proposal_version_id")

    op.drop_constraint(
        "fk_assignment_proposal_version",
        "reviewer_assignments",
        type_="foreignkey",
    )
    op.drop_column("reviewer_assignments", "proposal_version_id")
    op.drop_column("proposal_versions", "executive_summary")
