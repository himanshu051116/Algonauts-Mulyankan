import pytest
from fastapi import HTTPException

from app.models.proposal import RubricCriterion
from app.routers.reviews import _resolve_rubric_criterion_id


class Result:
    def __init__(self, item):
        self.item = item

    def scalar_one_or_none(self):
        return self.item


class FakeDb:
    def __init__(self, item):
        self.item = item

    async def execute(self, _statement):
        return Result(self.item)


@pytest.mark.asyncio
async def test_resolve_rubric_criterion_accepts_key():
    criterion = RubricCriterion(id="criterion-db-id", criterion_key="coal-specific-problem")
    assert await _resolve_rubric_criterion_id(FakeDb(criterion), "coal-specific-problem") == "criterion-db-id"


@pytest.mark.asyncio
async def test_resolve_rubric_criterion_accepts_database_id():
    criterion = RubricCriterion(id="criterion-db-id", criterion_key="coal-specific-problem")
    assert await _resolve_rubric_criterion_id(FakeDb(criterion), "criterion-db-id") == "criterion-db-id"


@pytest.mark.asyncio
async def test_resolve_rubric_criterion_rejects_unknown_value():
    with pytest.raises(HTTPException) as exc:
        await _resolve_rubric_criterion_id(FakeDb(None), "unknown-criterion")
    assert exc.value.status_code == 400
    assert "Unknown rubric criterion" in exc.value.detail


@pytest.mark.asyncio
async def test_resolve_rubric_criterion_rejects_empty_value():
    with pytest.raises(HTTPException) as exc:
        await _resolve_rubric_criterion_id(FakeDb(None), "")
    assert exc.value.status_code == 400
    assert exc.value.detail == "Criterion score is missing criterion_id"
