"""Operational model-versus-human monitoring metrics."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.proposal import ModelMonitoringMetric, ModelRun, ReviewerAssignment


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class ScalarListResult:
    def __init__(self, values):
        self.values = values

    class _Scalars:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    def scalars(self):
        return self._Scalars(self.values)


class FakeDb:
    def __init__(self, results):
        self.results = list(results)
        self.added = []

    async def execute(self, _statement):
        return self.results.pop(0)

    def add(self, item):
        self.added.append(item)


@pytest.mark.asyncio
async def test_review_monitoring_records_score_and_recommendation_deltas():
    from app.routers.reviews import _record_review_monitoring

    run = ModelRun(
        id="run-1",
        proposal_version_id="version-1",
        model_version_id="model-1",
        status="completed",
        total_score=72.0,
        completed_at=datetime.now(timezone.utc),
    )
    assignment = ReviewerAssignment(
        id="assignment-1",
        proposal_id="proposal-1",
        proposal_version_id="version-1",
        reviewer_id="reviewer-1",
        assigned_by="admin-1",
        role="technical",
        status="in_progress",
    )
    db = FakeDb([ScalarResult(run)])

    await _record_review_monitoring(db, assignment, 82.0, "approved")

    values = {item.metric_name: item.metric_value for item in db.added}
    assert values["expert_score_delta:assignment-1"] == 10.0
    assert values["expert_abs_error:assignment-1"] == 10.0
    assert values["expert_recommendation_disagreement:assignment-1"] == 1.0


@pytest.mark.asyncio
async def test_review_monitoring_marks_human_review_after_model_abstention():
    from app.routers.reviews import _record_review_monitoring

    run = ModelRun(
        id="run-2",
        proposal_version_id="version-2",
        model_version_id="model-1",
        status="completed",
        total_score=18.0,
        abstention_reason="insufficient evidence",
    )
    assignment = ReviewerAssignment(
        id="assignment-2",
        proposal_id="proposal-2",
        proposal_version_id="version-2",
        reviewer_id="reviewer-2",
        assigned_by="admin-1",
        role="financial",
        status="in_progress",
    )
    db = FakeDb([ScalarResult(run)])

    await _record_review_monitoring(db, assignment, 55.0, "revision")

    values = {item.metric_name: item.metric_value for item in db.added}
    assert values["expert_review_after_abstention:assignment-2"] == 1.0


@pytest.mark.asyncio
async def test_monitoring_endpoint_returns_persisted_metrics():
    from app.routers.governance import get_model_run_monitoring

    run = ModelRun(
        id="run-3",
        proposal_version_id="version-3",
        model_version_id="model-1",
        status="completed",
        total_score=64.0,
    )
    metric = ModelMonitoringMetric(
        id="metric-1",
        model_run_id=run.id,
        metric_name="expert_abs_error:assignment-3",
        metric_value=8.0,
        recorded_at=datetime.now(timezone.utc),
    )
    db = FakeDb([ScalarResult(run), ScalarListResult([metric])])

    response = await get_model_run_monitoring(
        model_run_id=run.id,
        current_user=None,  # dependency enforcement is tested at the API boundary
        db=db,
    )

    assert response.model_run_id == run.id
    assert response.model_score == 64.0
    assert len(response.metrics) == 1
    assert response.metrics[0].metric_value == 8.0
