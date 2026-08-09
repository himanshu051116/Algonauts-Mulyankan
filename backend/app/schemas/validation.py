from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.domain import AssignmentRole

ValidationStudyStatus = Literal["draft", "active", "frozen", "completed", "archived"]
ValidationPartition = Literal["development", "internal_test", "external_test", "shadow"]
ValidationCaseStatus = Literal["queued", "under_review", "ready", "compared", "excluded"]


class ValidationStudyCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    scheme_code: str = Field(default="MOC-ST", min_length=2, max_length=50)
    protocol_version: str = Field(
        default="expert-grounded-validation-v1", min_length=3, max_length=50
    )
    annotation_rulebook_version: str = Field(
        default="expert-annotation-rulebook-v1", min_length=3, max_length=50
    )
    shadow_mode: bool = True
    minimum_reviews_per_case: int = Field(default=2, ge=2, le=10)
    recommendation_policy: dict[str, Any] = Field(default_factory=dict)

    @field_validator("scheme_code")
    @classmethod
    def normalize_scheme_code(cls, value: str) -> str:
        return value.strip().upper()


class ValidationStudyStatusRequest(BaseModel):
    status: ValidationStudyStatus


class ValidationCaseCreateRequest(BaseModel):
    proposal_id: str = Field(min_length=1)
    proposal_version_number: int | None = Field(default=None, ge=1)
    partition: ValidationPartition = "shadow"


class ValidationCaseExcludeRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip()


class ValidationAssignmentCreateRequest(BaseModel):
    reviewer_email: str = Field(min_length=3, max_length=320)
    role: AssignmentRole = AssignmentRole.TECHNICAL

    @field_validator("reviewer_email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
            raise ValueError("A valid reviewer email is required")
        return cleaned


class ValidationStudyResponse(BaseModel):
    id: str
    name: str
    description: str | None
    scheme_id: str
    scheme_code: str
    rubric_version_id: str
    rubric_version: str
    model_version_id: str
    model_name: str
    model_version: str
    model_artifact_hash: str
    rubric_definition_hash: str
    protocol_version: str
    annotation_rulebook_version: str
    status: str
    shadow_mode: bool
    minimum_reviews_per_case: int
    recommendation_policy: dict[str, Any]
    created_by: str
    created_at: datetime
    activated_at: datetime | None
    frozen_at: datetime | None
    completed_at: datetime | None
    case_count: int = 0
    compared_case_count: int = 0


class ValidationStudyListResponse(BaseModel):
    studies: list[ValidationStudyResponse]


class ValidationCaseResponse(BaseModel):
    id: str
    study_id: str
    proposal_id: str
    proposal_version_id: str
    proposal_version_number: int
    proposal_title: str
    model_run_id: str
    partition: str
    status: str
    exclusion_reason: str | None
    included_by: str
    included_at: datetime
    comparison_ready_at: datetime | None
    assigned_reviewers: int = 0
    completed_reviews: int = 0
    minimum_reviews_required: int = 2
    model_output_blinded: bool = True


class ValidationCaseListResponse(BaseModel):
    study_id: str
    cases: list[ValidationCaseResponse]


class ValidationCriterionFormItem(BaseModel):
    criterion_id: str
    criterion_key: str | None
    category: str
    criterion: str
    maximum: float
    description: str | None
    order: int


class ValidationReviewFormResponse(BaseModel):
    assignment_id: str
    proposal_id: str
    proposal_version_id: str
    proposal_version_number: int
    proposal_title: str
    reviewer_role: str
    validation_case_id: str | None
    study_name: str | None
    protocol_version: str | None
    annotation_rulebook_version: str | None
    shadow_mode: bool
    model_output_hidden: bool
    rubric_version: str
    total_marks: int
    criteria: list[ValidationCriterionFormItem]


class ValidationMetricResponse(BaseModel):
    name: str
    value: float | None
    sample_size: int
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationReadinessResponse(BaseModel):
    scientifically_validated: bool = False
    status: str
    warnings: list[str]
    total_cases: int
    compared_cases: int
    completed_reviews: int
    minimum_reviews_per_case: int
    partitions: dict[str, int]


class ValidationStudySummaryResponse(BaseModel):
    study: ValidationStudyResponse
    readiness: ValidationReadinessResponse
    snapshot_group_id: str | None
    metrics: list[ValidationMetricResponse]
    computed_at: datetime | None


class ValidationComputeResponse(BaseModel):
    study_id: str
    snapshot_group_id: str
    compared_cases: int
    metrics_written: int
    warnings: list[str]
    message: str


class ValidationAssignmentResponse(BaseModel):
    assignment_id: str
    validation_case_id: str
    reviewer_id: str
    status: str
    blind: bool
    message: str
