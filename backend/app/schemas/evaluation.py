from datetime import datetime
from pydantic import BaseModel, Field


class RuleResultSchema(BaseModel):
    model_config = {"from_attributes": True}
    rule_id: str
    category: str
    field: str
    result: str
    evidence_coverage: float
    detail: str
    severity: str
    uncertainty_action: str
    source_reference: str | None = None


class CriterionScoreSchema(BaseModel):
    model_config = {"from_attributes": True}
    criterion_id: str
    label: str
    awarded_score: float | None
    maximum_score: float
    ordinal_grade: int | None
    criterion_status: str = "unresolved"
    released: bool = False
    evidence_coverage: float
    information_sufficiency: float
    evidence_count: int = 0
    evidence: list[dict]
    rejected_evidence: list[dict] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    rationale: str | None = None


class CategoryScoreSchema(BaseModel):
    model_config = {"from_attributes": True}
    category: str
    maximum: float
    awarded: float
    criteria: list[CriterionScoreSchema]


class EvaluationResponse(BaseModel):
    proposal_id: str
    status: str
    model_run_id: str | None = None
    rule_evaluation: dict | None = None
    scoring: dict | None = None
    document_audit: dict | None = None
    document_gate: dict | None = None
    prior_project_check: dict | None = None
    engine_version: str | None = None
    input_checksum: str | None = None
    output_checksum: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


class EvaluationRerunResponse(BaseModel):
    proposal_id: str
    status: str
    message: str
