from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.domain import AssignmentRole, ReviewRecommendation


class ReviewerAssignmentResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    proposal_id: str
    proposal_version_id: str
    proposal_version_number: int
    reviewer_id: str
    validation_case_id: str | None = None
    is_shadow_validation: bool = False
    validation_study_name: str | None = None
    role: str
    status: str
    is_blind: bool
    conflict_declared: bool | None = None
    conflict_notes: str | None = None
    assigned_at: datetime
    completed_at: datetime | None = None


class AssignmentListResponse(BaseModel):
    model_config = {"from_attributes": True}
    assignments: list[ReviewerAssignmentResponse]


class ReviewAssignRequest(BaseModel):
    proposal_id: str = Field(min_length=1)
    reviewer_email: str = Field(min_length=3, max_length=320)
    role: AssignmentRole = AssignmentRole.TECHNICAL

    @field_validator("reviewer_email")
    @classmethod
    def validate_email_shape(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
            raise ValueError("A valid reviewer email is required")
        return cleaned


class ReviewAssignResponse(BaseModel):
    assignment: ReviewerAssignmentResponse
    status: str
    message: str


class CriterionScoreRequest(BaseModel):
    criterion_id: str = Field(min_length=1, max_length=200)
    score: float = Field(ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_coverage: float | None = Field(default=None, ge=0, le=1)
    rationale: str | None = Field(default=None, max_length=5000)
    page_references: list[int] = Field(default_factory=list, max_length=100)


class ReviewSubmitRequest(BaseModel):
    total_score: float = Field(ge=0, le=100)
    recommendation: ReviewRecommendation
    notes: str | None = Field(default=None, max_length=10000)
    criterion_scores: list[CriterionScoreRequest] = Field(min_length=1, max_length=100)


class ReviewSubmitResponse(BaseModel):
    assignment_id: str
    status: str
    message: str


class CriterionScoreResponse(BaseModel):
    criterion_id: str
    criterion_key: str | None = None
    criterion: str
    maximum: float
    score: float
    confidence: float | None = None
    evidence_coverage: float | None = None
    rationale: str | None = None
    page_references: list[int] = Field(default_factory=list)


class ExpertReviewResponse(BaseModel):
    id: str
    assignment_id: str
    reviewer_id: str
    reviewer_role: str
    proposal_version_id: str
    proposal_version_number: int
    total_score: float | None
    recommendation: str | None
    notes: str | None
    submitted_at: datetime | None
    criterion_scores: list[CriterionScoreResponse]


class ProposalReviewsResponse(BaseModel):
    proposal_id: str
    reviews: list[ExpertReviewResponse]
