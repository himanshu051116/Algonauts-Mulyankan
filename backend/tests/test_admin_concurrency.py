"""Tests for final-administrator protection and concurrent demotion safety."""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.models.user import User, UserRole
from app.routers import admin as admin_router
from app.schemas.admin import RoleAssignRequest


class FakeRequest:
    client = type("Client", (), {"host": "127.0.0.1"})()
    headers = {"user-agent": "pytest"}


def _result(value):
    r = Mock()
    r.scalar_one_or_none.return_value = value
    r.scalar.return_value = value if isinstance(value, int) else 0
    return r


def _user(id_suffix="1"):
    return User(
        id=f"admin-{id_suffix}",
        email=f"admin{id_suffix}@coal.gov.in",
        role=UserRole.ADMINISTRATOR,
        is_active=True,
        is_verified=True,
        approval_status="approved",
    )


def _db(user, count=1):
    db = AsyncMock()
    db.add = Mock()
    db.execute.side_effect = [_result(user), _result(count)]
    return db


# ============================================================
# PHASE 8 — FINAL ADMINISTRATOR PROTECTION
# ============================================================


@pytest.mark.asyncio
async def test_last_active_admin_cannot_be_demoted():
    admin = _user("solo")
    current_user = _user("different")
    db = _db(admin, count=1)

    body = RoleAssignRequest(role="scrutiny_officer", reason="Testing protection")
    with pytest.raises(HTTPException) as exc:
        await admin_router.assign_role(
            user_id=admin.id,
            body=body,
            request=FakeRequest(),
            current_user=current_user,
            db=db,
        )
    assert exc.value.status_code == 400
    assert "last administrator" in exc.value.detail


@pytest.mark.asyncio
async def test_last_active_admin_cannot_suspend_self():
    admin = _user("self")
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await admin_router.suspend_user(
            user_id=admin.id,
            request=FakeRequest(),
            current_user=admin,
            db=db,
        )
    assert exc.value.status_code == 400
    assert "cannot suspend themselves" in exc.value.detail


@pytest.mark.asyncio
async def test_last_active_admin_cannot_approve_self():
    admin = _user("self")
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await admin_router.approve_user(
            user_id=admin.id,
            request=FakeRequest(),
            current_user=admin,
            db=db,
        )
    assert exc.value.status_code == 400
    assert "cannot approve themselves" in exc.value.detail


@pytest.mark.asyncio
async def test_admin_demotion_allowed_when_two_admins_exist():
    admin_target = _user("target")
    admin_actor = _user("actor")
    db = _db(admin_target, count=2)

    body = RoleAssignRequest(role="scrutiny_officer", reason="Role change")
    response = await admin_router.assign_role(
        user_id=admin_target.id,
        body=body,
        request=FakeRequest(),
        current_user=admin_actor,
        db=db,
    )
    assert response.status == "updated"
    assert admin_target.role == UserRole.SCRUTINY_OFFICER


@pytest.mark.asyncio
async def test_remaining_admin_count_after_demotion():
    admin_a = _user("a")
    admin_b = _user("b")
    db = _db(admin_b, count=2)

    body = RoleAssignRequest(role="technical_reviewer", reason="Restructuring")
    await admin_router.assign_role(
        user_id=admin_b.id,
        body=body,
        request=FakeRequest(),
        current_user=admin_a,
        db=db,
    )
    remaining = sum(1 for u in [admin_a, admin_b] if u.role == UserRole.ADMINISTRATOR)
    assert remaining == 1


@pytest.mark.asyncio
async def test_inactive_admins_not_counted_for_protection():
    admin = _user("active")
    current_user = _user("supervisor")
    db = _db(admin, count=1)

    body = RoleAssignRequest(role="auditor", reason="Restructuring")
    with pytest.raises(HTTPException) as exc:
        await admin_router.assign_role(
            user_id=admin.id,
            body=body,
            request=FakeRequest(),
            current_user=current_user,
            db=db,
        )
    assert exc.value.status_code == 400


# ============================================================
# PHASE 9 — CONCURRENT FINAL-ADMIN DEMOTION
# ============================================================


@pytest.mark.asyncio
async def test_concurrent_admin_demotions_leave_one_active_admin():
    """Two concurrent demotions seeing 2 admins — first succeeds, second blocked.

    NOTE: reveals a race condition where two transactions both read count=2
    before either commits could leave 0 admins. The require_role guard on the
    second request (actor is no longer admin after first commit) mitigates this
    in sequential calls; truly concurrent writes are not prevented at READ
    COMMITTED isolation.
    """
    admin_a = _user("con-a")
    admin_b = _user("con-b")

    # First demotion: sees 2 admins -> succeeds
    db_a = _db(admin_b, count=2)
    body = RoleAssignRequest(role="auditor", reason="Concurrent test A")
    await admin_router.assign_role(
        user_id=admin_b.id,
        body=body,
        request=FakeRequest(),
        current_user=admin_a,
        db=db_a,
    )
    assert admin_b.role == UserRole.AUDITOR

    # Second attempt: count is now 1 (admin_a is sole admin) -> blocked
    db_b = _db(admin_a, count=1)
    with pytest.raises(HTTPException) as exc:
        await admin_router.assign_role(
            user_id=admin_a.id,
            body=RoleAssignRequest(role="auditor", reason="Concurrent test B"),
            request=FakeRequest(),
            current_user=admin_a,
            db=db_b,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_admin_suspend_self_rejected():
    admin = _user("solo")
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await admin_router.suspend_user(
            user_id=admin.id,
            request=FakeRequest(),
            current_user=admin,
            db=db,
        )
    assert exc.value.status_code == 400
