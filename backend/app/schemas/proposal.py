from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ProposalCreate(BaseModel):
    title: str = Field(min_length=8, max_length=500)
    scheme_code: str = Field(min_length=2, max_length=50)
    executive_summary: str | None = Field(default=None, max_length=5000)

    @field_validator("title", "scheme_code")
    @classmethod
    def strip_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Value must not be blank")
        return cleaned

    @field_validator("executive_summary")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ProposalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=8, max_length=500)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Title must not be blank")
        return cleaned


class ProposalVersionCreate(BaseModel):
    executive_summary: str | None = Field(default=None, max_length=5000)

    @field_validator("executive_summary")
    @classmethod
    def strip_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ProposalVersionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    proposal_id: str
    version_number: int
    previous_version_id: str | None
    title: str
    executive_summary: str | None
    document_hash: str
    content_hash: str
    package_status: str
    package_hash: str | None
    package_policy_version: str | None
    package_confirmed_at: datetime | None
    created_at: datetime


class ProposalVersionListResponse(BaseModel):
    versions: list[ProposalVersionResponse]


class ProposalResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    title: str
    scheme_id: str
    status: str
    current_version: int
    owner_id: str
    executive_summary: str | None = None
    document_id: str | None = None
    document_file_name: str | None = None
    created_at: datetime
    updated_at: datetime


class ProposalListResponse(BaseModel):
    proposals: list[ProposalResponse]
    total: int
    skip: int
    limit: int


DocumentRole = Literal[
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
]


class UploadUrlRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=300)
    file_size: int = Field(gt=0)
    document_role: DocumentRole = "main_proposal"
    requirement_id: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("requirement_id")
    @classmethod
    def strip_requirement_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class UploadUrlResponse(BaseModel):
    upload_url: str
    upload_session_id: str
    document_id: str
    storage_path: str
    requirement_id: str | None = None
    expires_in: int


class UploadConfirmRequest(BaseModel):
    upload_session_id: str
    checksum: str | None = None


class DocumentDownloadResponse(BaseModel):
    document_id: str
    file_name: str
    download_url: str
    expires_in: int


class ExtractedFieldCorrectionRequest(BaseModel):
    value: str = Field(min_length=1, max_length=5000)
    reason: str = Field(min_length=3, max_length=5000)

    @field_validator("value", "reason")
    @classmethod
    def strip_correction_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Value must not be blank")
        return cleaned


class ExtractedFieldResponse(BaseModel):
    field_name: str
    extracted_value: str | None
    normalized_value: str | None
    manually_corrected_value: str | None
    effective_value: str | None
    original_text: str | None
    source_page: int | None
    source_section: str | None
    char_start: int | None
    char_end: int | None
    evidence_coverage: float | None
    validation_warnings: list
    conflict_status: str | None
    corrected_by: str | None
    corrected_at: datetime | None


class ExtractedFieldListResponse(BaseModel):
    document_id: str
    fields: list[ExtractedFieldResponse]


class SubmissionPackageDocumentResponse(BaseModel):
    id: str
    requirement_id: str | None
    document_role: str
    file_name: str
    file_type: str
    file_size: int
    sha256_hash: str
    is_primary: bool
    role_status: str
    has_extractable_text: bool
    upload_completed: bool
    created_at: str | None


class SubmissionPackageRequirementResponse(BaseModel):
    id: str
    label: str
    description: str
    document_role: str
    allowed_types: list[str]
    mandatory: bool
    max_size_mb: int
    status: str
    document_id: str | None
    reason: str | None


class SubmissionPackageResponse(BaseModel):
    proposal_id: str
    proposal_version_id: str
    proposal_version_number: int
    scheme_code: str
    policy_version: str
    package_status: str
    package_hash: str | None
    package_confirmed_at: datetime | None
    package_confirmed_by: str | None
    ready_to_confirm: bool
    missing_mandatory_requirements: list[str]
    invalid_requirements: list[str]
    unassigned_document_ids: list[str]
    requirements: list[SubmissionPackageRequirementResponse]
    documents: list[SubmissionPackageDocumentResponse]


class SubmissionPackageConfirmRequest(BaseModel):
    confirm_declared_roles: bool = True
