"""Tests for Redis/ARQ unavailability and database commit failure.

Phase 10: Redis/ARQ pool unavailable during submission/evaluation enqueue.
Phase 14: Database commit failure rollback.
"""

import types

import pytest
from fastapi import HTTPException

from app.models.user import User, UserRole
from app.schemas.admin import RoleAssignRequest


class FakeRequest:
    client = types.SimpleNamespace(host="127.0.0.1")
    headers = {"user-agent": "pytest"}


def fake_proposal(**kw):
    obj = types.SimpleNamespace(**{
        "id": "test-prop", "status": "draft", "scheme_id": "scheme-moc-st",
        "owner_id": "user-1", "title": "Test", "current_version": 1,
        "created_at": None, "updated_at": None,
    })
    for k, v in kw.items():
        setattr(obj, k, v)
    return obj


def fake_user(**kw):
    obj = types.SimpleNamespace(**{
        "id": "admin-1", "role": UserRole.ADMINISTRATOR,
        "email": "admin@test.gov.in", "is_active": True,
        "is_verified": True, "approval_status": "approved",
    })
    for k, v in kw.items():
        setattr(obj, k, v)
    return obj


class Result:
    def __init__(self, value):
        self._value = value
    def scalar_one_or_none(self):
        return self._value
    def scalar(self):
        return self._value if isinstance(self._value, int) else 0
    def scalars(self):
        return self


class Db:
    """Simple fake DB that returns pre-configured results sequentially."""
    def __init__(self, *results):
        self._results = list(results)
        self._call_index = 0
        self.commits = 0
        self.added = []
    async def execute(self, stmt):
        if self._call_index < len(self._results):
            v = self._results[self._call_index]
            self._call_index += 1
            return Result(v)
        return Result(None)
    def add(self, x):
        self.added.append(x)
    async def flush(self):
        pass
    async def commit(self):
        self.commits += 1


# ============================================================
# PHASE 10 — REDIS / ARQ POOL UNAVAILABLE
# ============================================================


@pytest.mark.asyncio
async def test_rerun_evaluation_redis_unavailable_returns_503(monkeypatch):
    """When ARQ is unavailable, rerun preserves the valid proposal state."""
    import app.routers.evaluations as evaluations_router

    async def broken_pool(*args, **kwargs):
        raise ConnectionError("Cannot connect to Redis")

    monkeypatch.setattr("arq.create_pool", broken_pool)

    proposal = fake_proposal(status="submitted")
    scheme = fake_proposal(id="sch-1", code="MOC-ST", is_active=True)
    version = fake_proposal(id="ver-1")
    db = Db(proposal, scheme, version, "document-1")

    with pytest.raises(HTTPException) as exc:
        await evaluations_router.rerun_evaluation(
            proposal_id=proposal.id,
            request=FakeRequest(),
            current_user=fake_user(),
            db=db,
        )
    assert exc.value.status_code == 503
    assert proposal.status == "submitted"
    assert "Redis" not in str(exc.value.detail)
    assert "temporarily unavailable" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_rerun_rejects_finalised_proposal():
    import app.routers.evaluations as evaluations_router

    proposal = fake_proposal(status="approved")
    db = Db(proposal)

    with pytest.raises(HTTPException) as exc:
        await evaluations_router.rerun_evaluation(
            proposal_id=proposal.id,
            request=FakeRequest(),
            current_user=fake_user(),
            db=db,
        )

    assert exc.value.status_code == 409
    assert "cannot be re-evaluated" in exc.value.detail


@pytest.mark.asyncio
async def test_rerun_requires_extracted_primary_document():
    import app.routers.evaluations as evaluations_router

    proposal = fake_proposal(status="submitted")
    scheme = fake_proposal(id="sch-1", code="MOC-ST", is_active=True)
    version = fake_proposal(id="ver-1")
    db = Db(proposal, scheme, version, None)

    with pytest.raises(HTTPException) as exc:
        await evaluations_router.rerun_evaluation(
            proposal_id=proposal.id,
            request=FakeRequest(),
            current_user=fake_user(),
            db=db,
        )

    assert exc.value.status_code == 409
    assert "no extracted primary document" in exc.value.detail


@pytest.mark.asyncio
async def test_submit_proposal_redis_unavailable_returns_503(monkeypatch):
    """When ARQ pool creation fails during submission, must return 503."""
    import app.routers.proposals as proposals_router

    async def broken_pool(*args, **kwargs):
        raise ConnectionError("Cannot connect to Redis")

    monkeypatch.setattr("arq.create_pool", broken_pool)

    proposal = fake_proposal(status="draft")
    scheme = fake_proposal(id="sch-1", code="MOC-ST")
    version = fake_proposal(
        id="ver-1",
        proposal_id=proposal.id,
        version_number=1,
        package_status="confirmed",
        package_hash="a" * 64,
        package_policy_version="v1",
    )

    async def confirmed_package(*args, **kwargs):
        return {
            "ready_to_confirm": True,
            "computed_package_hash": "a" * 64,
            "missing_mandatory_requirements": [],
            "invalid_requirements": [],
        }

    monkeypatch.setattr(
        proposals_router, "_submission_package_summary", confirmed_package
    )
    db = Db(proposal, scheme, version, "confirmed-doc-id")

    with pytest.raises(HTTPException) as exc:
        await proposals_router.submit_proposal(
            proposal_id=proposal.id,
            request=FakeRequest(),
            current_user=fake_user(id="user-1"),
            db=db,
        )
    assert exc.value.status_code == 503
    assert "temporarily unavailable" in exc.value.detail
    assert proposal.status == "submitted"


@pytest.mark.asyncio
async def test_submitted_proposal_can_retry_initial_queue(monkeypatch):
    import app.routers.proposals as proposals_router

    enqueued = []

    class Pool:
        async def enqueue_job(self, *args, **kwargs):
            enqueued.append((args, kwargs))

        async def aclose(self):
            pass

    async def available_pool(*args, **kwargs):
        return Pool()

    monkeypatch.setattr("arq.create_pool", available_pool)
    proposal = fake_proposal(status="submitted")
    scheme = fake_proposal(id="sch-1", code="MOC-ST")
    version = fake_proposal(
        id="ver-1",
        proposal_id=proposal.id,
        version_number=1,
        package_status="confirmed",
        package_hash="a" * 64,
        package_policy_version="v1",
    )

    async def confirmed_package(*args, **kwargs):
        return {
            "ready_to_confirm": True,
            "computed_package_hash": "a" * 64,
            "missing_mandatory_requirements": [],
            "invalid_requirements": [],
        }

    monkeypatch.setattr(
        proposals_router, "_submission_package_summary", confirmed_package
    )
    db = Db(proposal, scheme, version, "confirmed-doc-id")

    response = await proposals_router.submit_proposal(
        proposal_id=proposal.id,
        request=FakeRequest(),
        current_user=fake_user(id="user-1"),
        db=db,
    )

    assert response == {"id": proposal.id, "status": "evaluating"}
    assert proposal.status == "evaluating"
    assert len(enqueued) == 1


# ============================================================
# PHASE 14 — DATABASE TRANSITION FAILURE
# ============================================================


@pytest.mark.asyncio
async def test_admin_assign_role_commit_failure_rolls_back():
    """If commit fails after role change, the error propagates and in-memory role is set."""
    import sqlalchemy.exc
    from app.routers import admin as admin_router

    admin_target = User(id="target", email="target@coal.gov.in", role=UserRole.ADMINISTRATOR,
                        is_active=True, is_verified=True, approval_status="approved")
    admin_actor = User(id="actor", email="actor@coal.gov.in", role=UserRole.ADMINISTRATOR,
                       is_active=True, is_verified=True, approval_status="approved")

    class DbFail:
        def __init__(self):
            self.added = []
        async def execute(self, stmt):
            s = str(stmt.compile(compile_kwargs={"literal_binds": True}))
            if "count" in s.lower():
                return Result(2)
            return Result(admin_target)
        def add(self, x):
            self.added.append(x)
        async def flush(self):
            pass
        async def commit(self):
            raise sqlalchemy.exc.OperationalError(
                "database is locked", params={}, orig=Exception("DB unavailable")
            )

    db = DbFail()

    with pytest.raises(sqlalchemy.exc.OperationalError):
        await admin_router.assign_role(
            user_id=admin_target.id,
            body=RoleAssignRequest(role="scrutiny_officer", reason="Testing commit failure"),
            request=FakeRequest(),
            current_user=admin_actor,
            db=db,
        )

    assert admin_target.role == UserRole.SCRUTINY_OFFICER
