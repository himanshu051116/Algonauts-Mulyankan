import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.base import Base


class FundingScheme(Base):
    __tablename__ = "funding_schemes"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class GuidelineVersion(Base):
    __tablename__ = "guideline_versions"
    __table_args__ = (
        UniqueConstraint("scheme_id", "version", name="uq_guideline_scheme_version"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    scheme_id: Mapped[str] = mapped_column(
        ForeignKey("funding_schemes.id"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    supersedes_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    scheme = relationship("FundingScheme")


class RubricVersion(Base):
    __tablename__ = "rubric_versions"
    __table_args__ = (
        UniqueConstraint("scheme_id", "version", name="uq_rubric_scheme_version"),
        CheckConstraint("total_marks > 0", name="ck_rubric_total_marks_positive"),
        Index(
            "uq_active_rubric_per_scheme",
            "scheme_id",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    scheme_id: Mapped[str] = mapped_column(
        ForeignKey("funding_schemes.id"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    total_marks: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    scheme = relationship("FundingScheme")
    criteria = relationship("RubricCriterion", back_populates="rubric")


class RubricCriterion(Base):
    __tablename__ = "rubric_criteria"
    __table_args__ = (
        UniqueConstraint(
            "rubric_version_id", "criterion_key", name="uq_rubric_criterion_key"
        ),
        CheckConstraint("maximum >= 0", name="ck_rubric_criterion_maximum_nonnegative"),
        CheckConstraint("weight >= 0", name="ck_rubric_criterion_weight_nonnegative"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    rubric_version_id: Mapped[str] = mapped_column(
        ForeignKey("rubric_versions.id"), nullable=False
    )
    criterion_key: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(String(200), nullable=False)
    criterion: Mapped[str] = mapped_column(String(300), nullable=False)
    maximum: Mapped[float] = mapped_column(Float, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)

    rubric = relationship("RubricVersion", back_populates="criteria")


class RuleDefinition(Base):
    __tablename__ = "rule_definitions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    rule_id: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    guideline_version_id: Mapped[str] = mapped_column(
        ForeignKey("guideline_versions.id"), nullable=False
    )
    funding_scheme_id: Mapped[str] = mapped_column(
        ForeignKey("funding_schemes.id"), nullable=False
    )
    category: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # eligibility, financial, compliance
    field: Mapped[str] = mapped_column(String(200), nullable=False)
    operator: Mapped[str] = mapped_column(String(30), nullable=False)
    limit_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="error")
    uncertainty_action: Mapped[str] = mapped_column(String(30), default="review")
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    superseded_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Proposal(Base):
    __tablename__ = "proposals"
    __table_args__ = (
        CheckConstraint(
            "current_version >= 1", name="ck_proposal_current_version_positive"
        ),
        CheckConstraint(
            "status IN ('draft','revision_required','submitted','evaluating','human_review',"
            "'adjudication','committee_review','approved','rejected','withdrawn','error')",
            name="ck_proposal_status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    scheme_id: Mapped[str] = mapped_column(
        ForeignKey("funding_schemes.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        default="draft",
        nullable=False,
        index=True,
    )
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner = relationship("User", back_populates="proposals")
    versions = relationship(
        "ProposalVersion",
        back_populates="proposal",
        order_by="ProposalVersion.version_number.desc()",
    )
    reviewer_assignments = relationship("ReviewerAssignment", back_populates="proposal")


class ProposalVersion(Base):
    __tablename__ = "proposal_versions"
    __table_args__ = (
        UniqueConstraint(
            "proposal_id", "version_number", name="uq_proposal_version_number"
        ),
        CheckConstraint(
            "version_number >= 1", name="ck_proposal_version_number_positive"
        ),
        CheckConstraint(
            "package_status IN ('draft','incomplete','ready','confirmed','legacy_single_document')",
            name="ck_proposal_version_package_status",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("proposals.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("proposal_versions.id"), nullable=True
    )
    rubric_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("rubric_versions.id"), nullable=True
    )
    guideline_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("guideline_versions.id"), nullable=True
    )
    # Version-scoped title preserves the exact submitted/reviewed snapshot.
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    executive_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_hash: Mapped[str] = mapped_column(String(64), default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    structured_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    package_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft"
    )
    package_manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    package_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    package_policy_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    package_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    package_confirmed_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    proposal = relationship("Proposal", back_populates="versions")
    guideline_version = relationship("GuidelineVersion")
    rubric_version = relationship("RubricVersion")
    documents = relationship("ProposalDocument", back_populates="proposal_version")
    model_runs = relationship("ModelRun", back_populates="proposal_version")


class ProposalDocument(Base):
    __tablename__ = "proposal_documents"
    __table_args__ = (
        CheckConstraint("file_size > 0", name="ck_proposal_document_file_size_positive"),
        CheckConstraint(
            "document_role IN ('main_proposal','budget_annexure','workplan_annexure','pi_cv','team_cv','institution_profile','industry_support_letter','safety_document','environment_document','compliance_document','quotation','previous_project_report','reference_guideline','other','unknown')",
            name="ck_proposal_document_role",
        ),
        CheckConstraint(
            "role_status IN ('declared','confirmed','mismatch','uncertain','legacy_unverified')",
            name="ck_proposal_document_role_status",
        ),
        CheckConstraint(
            "role_confidence IS NULL OR (role_confidence >= 0 AND role_confidence <= 1)",
            name="ck_proposal_document_role_confidence",
        ),
        Index(
            "uq_primary_document_per_proposal_version",
            "proposal_version_id",
            unique=True,
            postgresql_where=text("is_primary AND superseded_at IS NULL"),
            sqlite_where=text("is_primary = 1 AND superseded_at IS NULL"),
        ),
        Index(
            "uq_active_document_requirement",
            "proposal_version_id",
            "requirement_id",
            unique=True,
            postgresql_where=text("requirement_id IS NOT NULL AND superseded_at IS NULL"),
            sqlite_where=text("requirement_id IS NOT NULL AND superseded_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    proposal_version_id: Mapped[str] = mapped_column(
        ForeignKey("proposal_versions.id"), nullable=False
    )
    requirement_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_name: Mapped[str] = mapped_column(String(300), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    malware_scan_result: Mapped[str | None] = mapped_column(String(30), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_pages: Mapped[list] = mapped_column(JSONB, default=list)
    upload_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Document authority is explicit so supporting files cannot become evidence
    # for unrelated criteria.  The current single-file UI declares main_proposal;
    # future package uploads may use the additional governed roles.
    document_role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="main_proposal"
    )
    classified_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    role_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="legacy_unverified"
    )
    role_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    role_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # One active primary document is authoritative for each proposal version.
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    proposal_version = relationship("ProposalVersion", back_populates="documents")
    pages = relationship("DocumentPage", back_populates="document")


class UploadSession(Base):
    __tablename__ = "upload_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','consumed','failed','expired')",
            name="ck_upload_session_status_valid",
        ),
        CheckConstraint("maximum_size > 0", name="ck_upload_session_maximum_size_positive"),
        CheckConstraint(
            "expected_size IS NULL OR expected_size > 0",
            name="ck_upload_session_expected_size_positive",
        ),
        CheckConstraint(
            "document_role IN ('main_proposal','budget_annexure','workplan_annexure','pi_cv','team_cv','institution_profile','industry_support_letter','safety_document','environment_document','compliance_document','quotation','previous_project_report','reference_guideline','other','unknown')",
            name="ck_upload_session_document_role",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("proposals.id"), nullable=False, index=True
    )
    proposal_version_id: Mapped[str] = mapped_column(
        ForeignKey("proposal_versions.id"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    expected_file_name: Mapped[str] = mapped_column(String(300), nullable=False)
    requirement_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    document_role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="main_proposal"
    )
    allowed_content_types: Mapped[list] = mapped_column(JSONB, default=list)
    maximum_size: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    owner = relationship("User")
    proposal = relationship("Proposal")
    proposal_version = relationship("ProposalVersion")


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_document_page_number"),
        CheckConstraint("page_number >= 1", name="ck_document_page_number_positive"),
        CheckConstraint(
            "word_count >= 0", name="ck_document_page_word_count_nonnegative"
        ),
        CheckConstraint(
            "ocr_confidence IS NULL OR (ocr_confidence >= 0 AND ocr_confidence <= 1)",
            name="ck_document_page_ocr_confidence",
        ),
        CheckConstraint(
            "extraction_completeness IS NULL OR (extraction_completeness >= 0 AND extraction_completeness <= 1)",
            name="ck_document_page_completeness",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("proposal_documents.id"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    extraction_completeness: Mapped[float | None] = mapped_column(Float, nullable=True)
    table_count: Mapped[int] = mapped_column(Integer, default=0)
    image_count: Mapped[int] = mapped_column(Integer, default=0)

    document = relationship("ProposalDocument", back_populates="pages")


class ProposalSection(Base):
    __tablename__ = "proposal_sections"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("proposal_documents.id"), nullable=False
    )
    section_type: Mapped[str] = mapped_column(String(50), nullable=False)
    heading: Mapped[str | None] = mapped_column(String(300), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)


class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "field_name", name="uq_extracted_field_document_name"
        ),
        CheckConstraint(
            "extraction_confidence IS NULL OR (extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="ck_extracted_field_confidence",
        ),
        CheckConstraint(
            "evidence_coverage IS NULL OR (evidence_coverage >= 0 AND evidence_coverage <= 1)",
            name="ck_extracted_field_coverage",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("proposal_documents.id"), nullable=False
    )
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    field_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_section: Mapped[str | None] = mapped_column(String(50), nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    validation_warnings: Mapped[list] = mapped_column(JSONB, default=list)
    manually_corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    corrected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    alternatives: Mapped[list] = mapped_column(JSONB, default=list)
    conflict_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="none"
    )


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("model_name", "version", name="uq_model_name_version"),
        CheckConstraint(
            "training_rows >= 0", name="ck_model_training_rows_nonnegative"
        ),
        CheckConstraint(
            "lifecycle_state IN ('bootstrap', 'candidate', 'shadow', "
            "'externally_tested', 'institutionally_accepted', 'retired')",
            name="ck_model_version_lifecycle_state",
        ),
        CheckConstraint(
            "quality_gate_report_hash IS NULL OR length(quality_gate_report_hash) = 64",
            name="ck_model_version_quality_report_hash",
        ),
        CheckConstraint(
            "lifecycle_state IN ('bootstrap', 'retired') "
            "OR quality_gate_report_hash IS NOT NULL",
            name="ck_model_version_promotion_evidence",
        ),
        Index(
            "uq_active_model_per_rubric",
            "rubric_version_id",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rubric_version_id: Mapped[str] = mapped_column(
        ForeignKey("rubric_versions.id"), nullable=False
    )
    training_rows: Mapped[int] = mapped_column(Integer, default=0)
    test_metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    lifecycle_state: Mapped[str] = mapped_column(
        String(30),
        default="bootstrap",
        server_default="bootstrap",
        nullable=False,
    )
    quality_gate_report_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ModelRun(Base):
    __tablename__ = "model_runs"
    __table_args__ = (
        CheckConstraint(
            "total_score IS NULL OR (total_score >= 0 AND total_score <= 100)",
            name="ck_model_run_total_score",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_model_run_confidence",
        ),
        CheckConstraint(
            "information_sufficiency IS NULL OR (information_sufficiency >= 0 AND information_sufficiency <= 1)",
            name="ck_model_run_information_sufficiency",
        ),
        CheckConstraint(
            "status IN ('queued','running','completed','failed')",
            name="ck_model_run_status_valid",
        ),
        CheckConstraint(
            "diagnostic_score IS NULL OR (diagnostic_score >= 0 AND diagnostic_score <= 100)",
            name="ck_model_run_diagnostic_score",
        ),
        CheckConstraint(
            "scoring_status IN ('pending','released','abstained','gate_rejected','manual_review','rules_only','configuration_error','legacy_unverified','failed')",
            name="ck_model_run_scoring_status",
        ),
        CheckConstraint(
            "total_score IS NULL OR scoring_status = 'released'",
            name="ck_model_run_total_requires_release",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    proposal_version_id: Mapped[str] = mapped_column(
        ForeignKey("proposal_versions.id"), nullable=False, index=True
    )
    model_version_id: Mapped[str] = mapped_column(
        ForeignKey("model_versions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    diagnostic_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    scoring_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending"
    )
    gate_result: Mapped[dict] = mapped_column(JSONB, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    information_sufficiency: Mapped[float | None] = mapped_column(Float, nullable=True)
    abstention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    extraction_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rule_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    trigger_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    rerun_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evaluation_payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    failure_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    failure_details: Mapped[dict] = mapped_column(JSONB, default=dict)
    random_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    proposal_version = relationship("ProposalVersion", back_populates="model_runs")
    model_version = relationship("ModelVersion")
    trigger_user = relationship("User")
    rule_results = relationship(
        "RuleResult", back_populates="model_run", cascade="all, delete-orphan"
    )
    criterion_predictions = relationship(
        "CriterionPrediction",
        back_populates="model_run",
        cascade="all, delete-orphan",
    )


class RuleResult(Base):
    __tablename__ = "rule_results"
    __table_args__ = (
        UniqueConstraint(
            "model_run_id", "rule_definition_id", name="uq_rule_result_run_definition"
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_rule_result_confidence",
        ),
        CheckConstraint(
            "evidence_coverage IS NULL OR (evidence_coverage >= 0 AND evidence_coverage <= 1)",
            name="ck_rule_result_coverage",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    model_run_id: Mapped[str] = mapped_column(
        ForeignKey("model_runs.id"), nullable=False
    )
    rule_definition_id: Mapped[str] = mapped_column(
        ForeignKey("rule_definitions.id"), nullable=False
    )
    rule_identifier: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    rule_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    result: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # explicit fail-closed rule status
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    input_payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_reference: Mapped[str | None] = mapped_column(String(50), nullable=True)
    section_reference: Mapped[str | None] = mapped_column(String(50), nullable=True)
    warnings: Mapped[list] = mapped_column(JSONB, default=list)

    model_run = relationship("ModelRun", back_populates="rule_results")


class CriterionPrediction(Base):
    __tablename__ = "criterion_predictions"
    __table_args__ = (
        UniqueConstraint(
            "model_run_id", "rubric_criterion_id", name="uq_prediction_run_criterion"
        ),
        CheckConstraint("maximum_score >= 0", name="ck_prediction_maximum_nonnegative"),
        CheckConstraint(
            "awarded_score IS NULL OR (awarded_score >= 0 AND awarded_score <= maximum_score)",
            name="ck_prediction_awarded_score",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_prediction_confidence",
        ),
        CheckConstraint(
            "evidence_coverage IS NULL OR (evidence_coverage >= 0 AND evidence_coverage <= 1)",
            name="ck_prediction_coverage",
        ),
        CheckConstraint(
            "information_sufficiency IS NULL OR (information_sufficiency >= 0 AND information_sufficiency <= 1)",
            name="ck_prediction_sufficiency",
        ),
        CheckConstraint(
            "criterion_status IN ('supported','partially_supported','contradicted','unresolved','not_applicable','extraction_uncertain','role_disallowed','legacy_unverified')",
            name="ck_prediction_criterion_status",
        ),
        CheckConstraint(
            "evidence_count >= 0",
            name="ck_prediction_evidence_count_nonnegative",
        ),
        CheckConstraint(
            "awarded_score IS NULL OR evidence_count > 0 OR criterion_status = 'legacy_unverified'",
            name="ck_prediction_score_requires_evidence",
        ),
        CheckConstraint(
            "awarded_score IS NULL OR released OR criterion_status = 'legacy_unverified'",
            name="ck_prediction_score_requires_release",
        ),
        CheckConstraint(
            "NOT released OR (awarded_score IS NOT NULL AND evidence_count > 0)",
            name="ck_prediction_release_requires_score_evidence",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    model_run_id: Mapped[str] = mapped_column(
        ForeignKey("model_runs.id"), nullable=False
    )
    rubric_criterion_id: Mapped[str] = mapped_column(
        ForeignKey("rubric_criteria.id"), nullable=False
    )
    ordinal_grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awarded_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    maximum_score: Mapped[float] = mapped_column(Float, nullable=False)
    category_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    information_sufficiency: Mapped[float | None] = mapped_column(Float, nullable=True)
    missing_evidence: Mapped[list] = mapped_column(JSONB, default=list)
    criterion_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unresolved"
    )
    released: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    abstention: Mapped[bool] = mapped_column(Boolean, default=False)
    model_source: Mapped[str] = mapped_column(String(30), default="rubric-keyword")
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list] = mapped_column(JSONB, default=list)

    model_run = relationship("ModelRun", back_populates="criterion_predictions")


class CriterionEvidence(Base):
    __tablename__ = "criterion_evidence"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    criterion_prediction_id: Mapped[str] = mapped_column(
        ForeignKey("criterion_predictions.id"), nullable=False
    )
    passage_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_section: Mapped[str | None] = mapped_column(String(50), nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    assertion_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    document_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    verification_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    verification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieval_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SimilarityMatch(Base):
    __tablename__ = "similarity_matches"
    __table_args__ = (
        UniqueConstraint(
            "model_run_id",
            "matched_proposal_version_id",
            name="uq_similarity_run_version",
        ),
        CheckConstraint(
            "similarity_score >= 0 AND similarity_score <= 1",
            name="ck_similarity_score",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    model_run_id: Mapped[str] = mapped_column(
        ForeignKey("model_runs.id"), nullable=False
    )
    matched_proposal_version_id: Mapped[str] = mapped_column(
        ForeignKey("proposal_versions.id"), nullable=False
    )
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    method: Mapped[str] = mapped_column(String(50), nullable=False)
    matched_passages: Mapped[list] = mapped_column(JSONB, default=list)
    review_flag: Mapped[str] = mapped_column(String(20), default="none")


class ValidationStudy(Base):
    __tablename__ = "validation_studies"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','active','frozen','completed','archived')",
            name="ck_validation_study_status",
        ),
        CheckConstraint(
            "minimum_reviews_per_case >= 2",
            name="ck_validation_study_min_reviews",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheme_id: Mapped[str] = mapped_column(
        ForeignKey("funding_schemes.id"), nullable=False, index=True
    )
    rubric_version_id: Mapped[str] = mapped_column(
        ForeignKey("rubric_versions.id"), nullable=False
    )
    model_version_id: Mapped[str] = mapped_column(
        ForeignKey("model_versions.id"), nullable=False
    )
    model_artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rubric_definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(50), nullable=False)
    annotation_rulebook_version: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft", index=True
    )
    shadow_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    minimum_reviews_per_case: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2
    )
    recommendation_policy: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    frozen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    scheme = relationship("FundingScheme")
    rubric_version = relationship("RubricVersion")
    model_version = relationship("ModelVersion")
    creator = relationship("User")
    cases = relationship(
        "ValidationCase",
        back_populates="study",
        cascade="all, delete-orphan",
    )


class ValidationCase(Base):
    __tablename__ = "validation_cases"
    __table_args__ = (
        UniqueConstraint(
            "study_id", "proposal_id", name="uq_validation_case_study_proposal"
        ),
        UniqueConstraint(
            "study_id",
            "proposal_version_id",
            name="uq_validation_case_study_version",
        ),
        CheckConstraint(
            "partition IN ('development','internal_test','external_test','shadow')",
            name="ck_validation_case_partition",
        ),
        CheckConstraint(
            "status IN ('queued','under_review','ready','compared','excluded')",
            name="ck_validation_case_status",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    study_id: Mapped[str] = mapped_column(
        ForeignKey("validation_studies.id"), nullable=False, index=True
    )
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("proposals.id"), nullable=False, index=True
    )
    proposal_version_id: Mapped[str] = mapped_column(
        ForeignKey("proposal_versions.id"), nullable=False, index=True
    )
    model_run_id: Mapped[str] = mapped_column(
        ForeignKey("model_runs.id"), nullable=False
    )
    partition: Mapped[str] = mapped_column(String(30), nullable=False, default="shadow")
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="queued", index=True
    )
    exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    included_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    included_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    comparison_ready_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    study = relationship("ValidationStudy", back_populates="cases")
    proposal = relationship("Proposal")
    proposal_version = relationship("ProposalVersion")
    model_run = relationship("ModelRun")
    includer = relationship("User")
    reviewer_assignments = relationship(
        "ReviewerAssignment", back_populates="validation_case"
    )
    consensus = relationship(
        "ValidationConsensus",
        uselist=False,
        back_populates="validation_case",
        cascade="all, delete-orphan",
    )
    comparison = relationship(
        "ShadowComparison",
        uselist=False,
        back_populates="validation_case",
        cascade="all, delete-orphan",
    )


class ValidationConsensus(Base):
    __tablename__ = "validation_consensus"
    __table_args__ = (
        UniqueConstraint(
            "validation_case_id", name="uq_validation_consensus_case"
        ),
        CheckConstraint(
            "expert_total_score >= 0 AND expert_total_score <= 100",
            name="ck_validation_consensus_score",
        ),
        CheckConstraint(
            "reviewer_count >= 2",
            name="ck_validation_consensus_reviewers",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    validation_case_id: Mapped[str] = mapped_column(
        ForeignKey("validation_cases.id"), nullable=False
    )
    expert_total_score: Mapped[float] = mapped_column(Float, nullable=False)
    expert_recommendation: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reviewer_count: Mapped[int] = mapped_column(Integer, nullable=False)
    consensus_method: Mapped[str] = mapped_column(
        String(50), nullable=False, default="mean_of_blind_reviews"
    )
    criterion_scores: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    agreement_metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    validation_case = relationship("ValidationCase", back_populates="consensus")


class ShadowComparison(Base):
    __tablename__ = "shadow_comparisons"
    __table_args__ = (
        UniqueConstraint(
            "validation_case_id", name="uq_shadow_comparison_case"
        ),
        CheckConstraint(
            "model_total_score IS NULL OR (model_total_score >= 0 AND model_total_score <= 100)",
            name="ck_shadow_comparison_model_score",
        ),
        CheckConstraint(
            "expert_total_score >= 0 AND expert_total_score <= 100",
            name="ck_shadow_comparison_expert_score",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    validation_case_id: Mapped[str] = mapped_column(
        ForeignKey("validation_cases.id"), nullable=False
    )
    model_total_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    expert_total_score: Mapped[float] = mapped_column(Float, nullable=False)
    score_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    absolute_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    squared_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_scoring_status: Mapped[str] = mapped_column(String(30), nullable=False)
    model_released: Mapped[bool] = mapped_column(Boolean, nullable=False)
    model_recommendation: Mapped[str | None] = mapped_column(String(30), nullable=True)
    expert_recommendation: Mapped[str | None] = mapped_column(String(30), nullable=True)
    recommendation_agreement: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    model_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_information_sufficiency: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    validation_case = relationship("ValidationCase", back_populates="comparison")


class ValidationMetricSnapshot(Base):
    __tablename__ = "validation_metric_snapshots"
    __table_args__ = (
        CheckConstraint(
            "partition IN ('all','development','internal_test','external_test','shadow')",
            name="ck_validation_metric_partition",
        ),
        CheckConstraint(
            "sample_size >= 0", name="ck_validation_metric_sample_size"
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    study_id: Mapped[str] = mapped_column(
        ForeignKey("validation_studies.id"), nullable=False, index=True
    )
    snapshot_group_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    partition: Mapped[str] = mapped_column(String(30), nullable=False, default="all")
    metric_name: Mapped[str] = mapped_column(String(120), nullable=False)
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    study = relationship("ValidationStudy")


class ReviewerAssignment(Base):
    __tablename__ = "reviewer_assignments"
    __table_args__ = (
        UniqueConstraint(
            "proposal_version_id",
            "reviewer_id",
            name="uq_assignment_version_reviewer",
        ),
        CheckConstraint(
            "role IN ('technical','financial')",
            name="ck_assignment_role_valid",
        ),
        CheckConstraint(
            "status IN ('pending','accepted','in_progress','conflict_declared','completed','cancelled')",
            name="ck_assignment_status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), nullable=False)
    proposal_version_id: Mapped[str] = mapped_column(
        ForeignKey("proposal_versions.id"), nullable=False
    )
    validation_case_id: Mapped[str | None] = mapped_column(
        ForeignKey("validation_cases.id"), nullable=True, index=True
    )
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # technical, financial
    status: Mapped[str] = mapped_column(String(30), default="pending")
    is_blind: Mapped[bool] = mapped_column(Boolean, default=True)
    conflict_declared: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    conflict_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    proposal = relationship("Proposal", back_populates="reviewer_assignments")
    proposal_version = relationship("ProposalVersion")
    reviewer = relationship(
        "User",
        back_populates="review_assignments",
        foreign_keys=[reviewer_id],
    )
    assigner = relationship(
        "User",
        back_populates="assigned_review_assignments",
        foreign_keys=[assigned_by],
    )
    review = relationship("ExpertReview", uselist=False, back_populates="assignment")
    validation_case = relationship(
        "ValidationCase", back_populates="reviewer_assignments"
    )


class ExpertReview(Base):
    __tablename__ = "expert_reviews"
    __table_args__ = (
        CheckConstraint(
            "total_score IS NULL OR (total_score >= 0 AND total_score <= 100)",
            name="ck_expert_review_total_score",
        ),
        CheckConstraint(
            "recommendation IS NULL OR recommendation IN ('approved','revision','rejected')",
            name="ck_expert_review_recommendation_valid",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    assignment_id: Mapped[str] = mapped_column(
        ForeignKey("reviewer_assignments.id"), nullable=False, unique=True
    )
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    annotation_protocol_version: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    annotation_rulebook_version: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    model_output_visible_at_submission: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    is_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    assignment = relationship("ReviewerAssignment", back_populates="review")
    criterion_scores = relationship("ExpertCriterionScore", back_populates="review")


class ExpertCriterionScore(Base):
    __tablename__ = "expert_criterion_scores"
    __table_args__ = (
        UniqueConstraint(
            "review_id", "rubric_criterion_id", name="uq_expert_score_review_criterion"
        ),
        CheckConstraint("score >= 0", name="ck_expert_score_nonnegative"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_expert_score_confidence",
        ),
        CheckConstraint(
            "evidence_coverage IS NULL OR (evidence_coverage >= 0 AND evidence_coverage <= 1)",
            name="ck_expert_score_coverage",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    review_id: Mapped[str] = mapped_column(
        ForeignKey("expert_reviews.id"), nullable=False
    )
    rubric_criterion_id: Mapped[str] = mapped_column(
        ForeignKey("rubric_criteria.id"), nullable=False
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_references: Mapped[list] = mapped_column(JSONB, default=list)

    review = relationship("ExpertReview", back_populates="criterion_scores")


class Adjudication(Base):
    __tablename__ = "adjudications"
    __table_args__ = (
        CheckConstraint(
            "resolved_score IS NULL OR (resolved_score >= 0 AND resolved_score <= 100)",
            name="ck_adjudication_score",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), nullable=False)
    proposal_version_id: Mapped[str] = mapped_column(
        ForeignKey("proposal_versions.id"), nullable=False
    )
    adjudicator_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    criterion_id: Mapped[str | None] = mapped_column(
        ForeignKey("rubric_criteria.id"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CommitteeDecision(Base):
    __tablename__ = "committee_decisions"
    __table_args__ = (
        UniqueConstraint(
            "proposal_version_id",
            name="uq_committee_decision_proposal_version",
        ),
        CheckConstraint(
            "decision IN ('approved','rejected','revision_required')",
            name="ck_committee_decision_valid",
        ),
        CheckConstraint(
            "model_score_at_decision IS NULL OR (model_score_at_decision >= 0 AND model_score_at_decision <= 100)",
            name="ck_committee_model_score",
        ),
        CheckConstraint(
            "expert_score_at_decision IS NULL OR (expert_score_at_decision >= 0 AND expert_score_at_decision <= 100)",
            name="ck_committee_expert_score",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), nullable=False)
    proposal_version_id: Mapped[str] = mapped_column(
        ForeignKey("proposal_versions.id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    model_score_at_decision: Mapped[float | None] = mapped_column(Float, nullable=True)
    expert_score_at_decision: Mapped[float | None] = mapped_column(Float, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String, nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="info")
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ModelMonitoringMetric(Base):
    __tablename__ = "model_monitoring_metrics"
    __table_args__ = (
        UniqueConstraint(
            "model_run_id", "metric_name", name="uq_monitoring_run_metric"
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    model_run_id: Mapped[str] = mapped_column(
        ForeignKey("model_runs.id"), nullable=False
    )
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
