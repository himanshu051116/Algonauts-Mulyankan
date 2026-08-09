import pytest
from fastapi import HTTPException

from app.models.proposal import Proposal
from app.models.user import User, UserRole
from app.services.access import get_proposal_for_user, user_can_access_proposal


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDb:
    def __init__(self, *values):
        self.values = list(values)

    async def execute(self, _statement):
        return Result(self.values.pop(0) if self.values else None)


def user(user_id: str, role: UserRole) -> User:
    return User(
        id=user_id,
        email=f"{user_id}@example.gov.in",
        role=role,
        is_active=True,
        is_verified=True,
        approval_status="approved",
    )


def proposal(owner_id: str = "owner") -> Proposal:
    return Proposal(id="proposal-1", owner_id=owner_id, scheme_id="scheme-1", title="Test")


@pytest.mark.asyncio
async def test_owner_and_oversight_roles_can_access():
    item = proposal()
    assert await user_can_access_proposal(FakeDb(), user("owner", UserRole.APPLICANT), item)
    assert await user_can_access_proposal(FakeDb(), user("admin", UserRole.ADMINISTRATOR), item)


@pytest.mark.asyncio
async def test_unassigned_reviewer_cannot_access():
    item = proposal()
    assert not await user_can_access_proposal(
        FakeDb(None), user("reviewer", UserRole.TECHNICAL_REVIEWER), item
    )


@pytest.mark.asyncio
async def test_assigned_reviewer_can_access():
    item = proposal()
    assert await user_can_access_proposal(
        FakeDb("assignment-id"), user("reviewer", UserRole.TECHNICAL_REVIEWER), item
    )


@pytest.mark.asyncio
async def test_concealed_denial_returns_not_found():
    item = proposal()
    with pytest.raises(HTTPException) as exc:
        await get_proposal_for_user(
            FakeDb(item),
            user("other-applicant", UserRole.APPLICANT),
            item.id,
            conceal_existence=True,
        )
    assert exc.value.status_code == 404
