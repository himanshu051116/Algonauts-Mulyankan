from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.domain import CommitteeDecisionValue


class AdjudicationCreate(BaseModel):
    criterion_id: str | None = Field(default=None, max_length=200)
    reason: str = Field(min_length=10, max_length=10000)
    resolved_score: float | None = Field(default=None, ge=0, le=100)

    @field_validator("criterion_id")
    @classmethod
    def clean_criterion(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return value.strip()


class AdjudicationResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    proposal_id: str
    proposal_version_id: str
    adjudicator_id: str
    criterion_id: str | None
    reason: str
    resolved_score: float | None
    created_at: datetime


class AdjudicationListResponse(BaseModel):
    proposal_id: str
    adjudications: list[AdjudicationResponse]


class CommitteeDecisionCreate(BaseModel):
    decision: CommitteeDecisionValue
    decision_notes: str = Field(min_length=10, max_length=20000)

    @field_validator("decision_notes")
    @classmethod
    def clean_notes(cls, value: str) -> str:
        return value.strip()


class CommitteeDecisionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    proposal_id: str
    proposal_version_id: str
    decision: str
    decision_notes: str | None
    decided_by: str
    model_score_at_decision: float | None
    expert_score_at_decision: float | None
    decided_at: datetime


class ModelMonitoringMetricResponse(BaseModel):
    model_config = {"from_attributes": True}

    metric_name: str
    metric_value: float
    recorded_at: datetime


class ModelMonitoringRunResponse(BaseModel):
    model_run_id: str
    proposal_version_id: str
    model_score: float | None
    abstention_reason: str | None
    metrics: list[ModelMonitoringMetricResponse]
