"""Initial schema: all tables

Revision ID: 609a290ee409
Revises:
Create Date: 2026-07-04 01:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "609a290ee409"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enum types
    user_role_enum = postgresql.ENUM(
        "applicant",
        "scrutiny_officer",
        "technical_reviewer",
        "financial_reviewer",
        "senior_adjudicator",
        "committee_secretariat",
        "administrator",
        "auditor",
        "ml_engineer",
        name="user_role",
        create_type=False,
    )
    postgresql.ENUM(
        "applicant",
        "scrutiny_officer",
        "technical_reviewer",
        "financial_reviewer",
        "senior_adjudicator",
        "committee_secretariat",
        "administrator",
        "auditor",
        "ml_engineer",
        name="user_role",
    ).create(op.get_bind(), checkfirst=True)

    # Users
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, index=True, unique=True),
        sa.Column("role", user_role_enum, nullable=False, server_default="applicant"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("full_name", sa.String(200), nullable=True),
        sa.Column("organisation", sa.String(300), nullable=True),
        sa.Column("expertise", sa.Text(), nullable=True),
        sa.Column("experience_years", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("conflict_declarations", sa.Text(), nullable=True),
        sa.Column("approval_status", sa.String(30), nullable=True, server_default="pending"),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Funding schemes
    op.create_table(
        "funding_schemes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, index=True, unique=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Guideline versions
    op.create_table(
        "guideline_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("scheme_id", sa.String(), sa.ForeignKey("funding_schemes.id"), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_version", sa.String(20), nullable=True),
        sa.Column("content", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Rubric versions
    op.create_table(
        "rubric_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("scheme_id", sa.String(), sa.ForeignKey("funding_schemes.id"), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_marks", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Rubric criteria
    op.create_table(
        "rubric_criteria",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("rubric_version_id", sa.String(), sa.ForeignKey("rubric_versions.id"), nullable=False),
        sa.Column("category", sa.String(200), nullable=False),
        sa.Column("criterion", sa.String(300), nullable=False),
        sa.Column("maximum", sa.Float(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    # Rule definitions
    op.create_table(
        "rule_definitions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("rule_id", sa.String(100), nullable=False, index=True, unique=True),
        sa.Column("guideline_version_id", sa.String(), sa.ForeignKey("guideline_versions.id"), nullable=False),
        sa.Column("funding_scheme_id", sa.String(), sa.ForeignKey("funding_schemes.id"), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("field", sa.String(200), nullable=False),
        sa.Column("operator", sa.String(30), nullable=False),
        sa.Column("limit_value", sa.String(200), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False, server_default="error"),
        sa.Column("uncertainty_action", sa.String(30), nullable=False, server_default="review"),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_by", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Proposals
    op.create_table(
        "proposals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_id", sa.String(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("scheme_id", sa.String(), sa.ForeignKey("funding_schemes.id"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft", index=True),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Proposal versions
    op.create_table(
        "proposal_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("proposal_id", sa.String(), sa.ForeignKey("proposals.id"), nullable=False, index=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("previous_version_id", sa.String(), sa.ForeignKey("proposal_versions.id"), nullable=True),
        sa.Column("rubric_version_id", sa.String(), sa.ForeignKey("rubric_versions.id"), nullable=True),
        sa.Column("guideline_version_id", sa.String(), sa.ForeignKey("guideline_versions.id"), nullable=True),
        sa.Column("document_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("structured_data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Proposal documents
    op.create_table(
        "proposal_documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("proposal_version_id", sa.String(), sa.ForeignKey("proposal_versions.id"), nullable=False),
        sa.Column("file_name", sa.String(300), nullable=False),
        sa.Column("file_type", sa.String(20), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column("malware_scan_result", sa.String(30), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extraction_version", sa.String(20), nullable=True),
        sa.Column("ocr_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ocr_pages", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("upload_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Document pages
    op.create_table(
        "document_pages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), sa.ForeignKey("proposal_documents.id"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ocr_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("table_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("image_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    # Proposal sections
    op.create_table(
        "proposal_sections",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), sa.ForeignKey("proposal_documents.id"), nullable=False),
        sa.Column("section_type", sa.String(50), nullable=False),
        sa.Column("heading", sa.String(300), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("start_page", sa.Integer(), nullable=True),
        sa.Column("end_page", sa.Integer(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
    )

    # Extracted fields
    op.create_table(
        "extracted_fields",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), sa.ForeignKey("proposal_documents.id"), nullable=False),
        sa.Column("field_name", sa.String(100), nullable=False),
        sa.Column("field_value", sa.Text(), nullable=True),
        sa.Column("field_unit", sa.String(50), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_section", sa.String(50), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column("alternatives", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("conflict_status", sa.String(20), nullable=True, server_default="none"),
    )

    # Model versions
    op.create_table(
        "model_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("artifact_hash", sa.String(64), nullable=False),
        sa.Column("rubric_version_id", sa.String(), sa.ForeignKey("rubric_versions.id"), nullable=False),
        sa.Column("training_rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("test_metrics", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Model runs
    op.create_table(
        "model_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("proposal_version_id", sa.String(), sa.ForeignKey("proposal_versions.id"), nullable=False, index=True),
        sa.Column("model_version_id", sa.String(), sa.ForeignKey("model_versions.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("total_score", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("abstention_reason", sa.Text(), nullable=True),
        sa.Column("extraction_version", sa.String(20), nullable=True),
        sa.Column("rule_version", sa.String(20), nullable=True),
        sa.Column("random_seed", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Rule results
    op.create_table(
        "rule_results",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("model_run_id", sa.String(), sa.ForeignKey("model_runs.id"), nullable=False),
        sa.Column("rule_definition_id", sa.String(), sa.ForeignKey("rule_definitions.id"), nullable=False),
        sa.Column("result", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    # Criterion predictions
    op.create_table(
        "criterion_predictions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("model_run_id", sa.String(), sa.ForeignKey("model_runs.id"), nullable=False),
        sa.Column("rubric_criterion_id", sa.String(), sa.ForeignKey("rubric_criteria.id"), nullable=False),
        sa.Column("ordinal_grade", sa.Integer(), nullable=True),
        sa.Column("awarded_score", sa.Float(), nullable=True),
        sa.Column("maximum_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("model_source", sa.String(30), nullable=False, server_default="rubric-keyword"),
        sa.Column("rationale", sa.Text(), nullable=True),
    )

    # Criterion evidence
    op.create_table(
        "criterion_evidence",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("criterion_prediction_id", sa.String(), sa.ForeignKey("criterion_predictions.id"), nullable=False),
        sa.Column("passage_text", sa.Text(), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_section", sa.String(50), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("assertion_state", sa.String(30), nullable=True),
        sa.Column("retrieval_rank", sa.Integer(), nullable=True),
    )

    # Similarity matches
    op.create_table(
        "similarity_matches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("model_run_id", sa.String(), sa.ForeignKey("model_runs.id"), nullable=False),
        sa.Column("matched_proposal_version_id", sa.String(), sa.ForeignKey("proposal_versions.id"), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column("method", sa.String(50), nullable=False),
        sa.Column("matched_passages", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("review_flag", sa.String(20), nullable=False, server_default="none"),
    )

    # Reviewer assignments
    op.create_table(
        "reviewer_assignments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("proposal_id", sa.String(), sa.ForeignKey("proposals.id"), nullable=False),
        sa.Column("reviewer_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assigned_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("is_blind", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("conflict_declared", sa.Boolean(), nullable=True),
        sa.Column("conflict_notes", sa.Text(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Expert reviews
    op.create_table(
        "expert_reviews",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("assignment_id", sa.String(), sa.ForeignKey("reviewer_assignments.id"), nullable=False, unique=True),
        sa.Column("total_score", sa.Float(), nullable=True),
        sa.Column("recommendation", sa.String(30), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_submitted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Expert criterion scores
    op.create_table(
        "expert_criterion_scores",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("review_id", sa.String(), sa.ForeignKey("expert_reviews.id"), nullable=False),
        sa.Column("rubric_criterion_id", sa.String(), sa.ForeignKey("rubric_criteria.id"), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("page_references", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )

    # Adjudications
    op.create_table(
        "adjudications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("proposal_id", sa.String(), sa.ForeignKey("proposals.id"), nullable=False),
        sa.Column("adjudicator_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("criterion_id", sa.String(), sa.ForeignKey("rubric_criteria.id"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("resolved_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Committee decisions
    op.create_table(
        "committee_decisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("proposal_id", sa.String(), sa.ForeignKey("proposals.id"), nullable=False, unique=True),
        sa.Column("decision", sa.String(50), nullable=False),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("model_score_at_decision", sa.Float(), nullable=True),
        sa.Column("expert_score_at_decision", sa.Float(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Audit events
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False, index=True),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.String(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Security events
    op.create_table(
        "security_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_type", sa.String(50), nullable=False, index=True),
        sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Model monitoring metrics
    op.create_table(
        "model_monitoring_metrics",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("model_run_id", sa.String(), sa.ForeignKey("model_runs.id"), nullable=False),
        sa.Column("metric_name", sa.String(100), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("model_monitoring_metrics")
    op.drop_table("security_events")
    op.drop_table("audit_events")
    op.drop_table("committee_decisions")
    op.drop_table("adjudications")
    op.drop_table("expert_criterion_scores")
    op.drop_table("expert_reviews")
    op.drop_table("reviewer_assignments")
    op.drop_table("similarity_matches")
    op.drop_table("criterion_evidence")
    op.drop_table("criterion_predictions")
    op.drop_table("rule_results")
    op.drop_table("model_runs")
    op.drop_table("model_versions")
    op.drop_table("extracted_fields")
    op.drop_table("proposal_sections")
    op.drop_table("document_pages")
    op.drop_table("proposal_documents")
    op.drop_table("proposal_versions")
    op.drop_table("proposals")
    op.drop_table("rule_definitions")
    op.drop_table("rubric_criteria")
    op.drop_table("rubric_versions")
    op.drop_table("guideline_versions")
    op.drop_table("funding_schemes")
    op.drop_table("users")
    postgresql.ENUM(name="user_role").drop(op.get_bind(), checkfirst=True)
