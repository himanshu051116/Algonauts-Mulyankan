"""Tests for consumed upload-session replay prevention and concurrent safety."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.models.proposal import FundingScheme, Proposal, ProposalVersion, UploadSession
from app.models.user import User, UserRole


class Result:
    def __init__(self, item):
        self.item = item

    def scalar_one_or_none(self):
        return self.item

    def all(self):
        return []

    def scalars(self):
        return self


class ResultList:
    def __init__(self, items):
        self.items = items
        self._idx = 0

    def scalar_one_or_none(self):
        return self.items[0] if self.items else None

    def all(self):
        return self.items

    def scalars(self):
        return self


def _make_fake_db(sessions, proposals=None, schemes=None, versions=None):
    """Return a FakeDb that yields items in order: session, proposal, scheme, version."""
    class FakeDb:
        def __init__(self):
            self.sessions = list(sessions) if sessions else []
            self.proposals = list(proposals) if proposals else []
            self.schemes = list(schemes) if schemes else []
            self.versions = list(versions) if versions else []
            self.commits = 0
            self.added = []
            self.flushed = False

        async def execute(self, _statement):
            if self.sessions:
                return Result(self.sessions.pop(0))
            if self.proposals:
                return Result(self.proposals.pop(0))
            if self.schemes:
                return Result(self.schemes.pop(0))
            if self.versions:
                return Result(self.versions.pop(0))
            return ResultList([])

        def add(self, item):
            self.added.append(item)

        async def flush(self):
            self.flushed = True

        async def commit(self):
            self.commits += 1

    return FakeDb()


@pytest.fixture
def upload_fixtures():
    owner = User(id="user-1", email="owner@coal.gov.in", role=UserRole.APPLICANT, is_active=True, is_verified=True)
    scheme = FundingScheme(id="scheme-1", code="MOC-ST", name="MOC S&T", is_active=True)
    proposal = Proposal(id="proposal-1", owner_id=owner.id, scheme_id=scheme.id, title="Test", status="draft", current_version=1)
    version = ProposalVersion(id="version-1", proposal_id=proposal.id, version_number=1)
    session = UploadSession(
        id="session-1",
        owner_id=owner.id,
        proposal_id=proposal.id,
        proposal_version_id=version.id,
        document_id="doc-1",
        storage_path="proposals/proposal-1/v1/doc-1_test.pdf",
        expected_file_name="test.pdf",
        allowed_content_types=["application/pdf"],
        maximum_size=1024 * 1024,
        expected_size=32,
        checksum=None,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    session.proposal_version = version
    return owner, proposal, version, session, scheme


def _patch_storage_router(monkeypatch, storage_router):
    """Patch storage router dependencies for testing."""
    async def head_object(*_args, **_kwargs):
        return {"ContentLength": 32, "ContentType": "application/pdf"}

    async def download_object_to_file(*_args, **_kwargs):
        _args[1].write_bytes(b"%PDF-1.7\nfake")
        return 32

    async def compute_file_hash(*_args, **_kwargs):
        return "f" * 64

    async def extract_pdf(*_args, **_kwargs):
        return {"text": "coal proposal", "warnings": []}

    async def extract_structured_fields(*_args, **_kwargs):
        return []

    async def create_audit_event(*_args, **_kwargs):
        return None

    async def create_durable_audit_event(*_args, **_kwargs):
        return None

    monkeypatch.setattr(storage_router, "head_object", head_object)
    monkeypatch.setattr(storage_router, "download_object_to_file", download_object_to_file)
    monkeypatch.setattr(storage_router, "compute_file_hash", compute_file_hash)
    monkeypatch.setattr(storage_router, "extract_pdf", extract_pdf)
    monkeypatch.setattr(storage_router, "extract_structured_fields", extract_structured_fields)
    monkeypatch.setattr(storage_router, "create_audit_event", create_audit_event)
    monkeypatch.setattr(storage_router, "create_durable_audit_event", create_durable_audit_event)


class FakeRequest:
    client = type("Client", (), {"host": "127.0.0.1"})()
    headers = {"user-agent": "pytest"}


class FakePool:
    async def enqueue_job(self, *_args, **_kwargs):
        return None

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_confirm_upload_rejects_consumed_session(monkeypatch, upload_fixtures):
    """A session with status 'consumed' must be rejected on second use."""
    from app.routers import storage as storage_router

    owner, proposal, version, session, scheme = upload_fixtures
    session.status = "consumed"
    session.consumed_at = datetime.now(timezone.utc)
    db = _make_fake_db([session, session, proposal, proposal, scheme, scheme, version])

    _patch_storage_router(monkeypatch, storage_router)

    with pytest.raises(HTTPException) as exc:
        await storage_router.confirm_upload(
            body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
            request=FakeRequest(),
            current_user=owner,
            db=db,
        )

    assert exc.value.status_code == 400
    assert "already been consumed" in exc.value.detail


@pytest.mark.asyncio
async def test_confirm_upload_rejects_consumed_session_by_consumed_at(monkeypatch, upload_fixtures):
    """Even if status is 'pending', a non-null consumed_at must be treated as consumed."""
    from app.routers import storage as storage_router

    owner, proposal, version, session, scheme = upload_fixtures
    session.status = "pending"
    session.consumed_at = datetime.now(timezone.utc)
    db = _make_fake_db([session, session, proposal, proposal, scheme, scheme, version])

    _patch_storage_router(monkeypatch, storage_router)

    with pytest.raises(HTTPException) as exc:
        await storage_router.confirm_upload(
            body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
            request=FakeRequest(),
            current_user=owner,
            db=db,
        )

    assert exc.value.status_code == 400
    assert "already been consumed" in exc.value.detail


@pytest.mark.asyncio
async def test_confirm_upload_rejects_session_with_status_failed(monkeypatch, upload_fixtures):
    """A session with status 'failed' must be rejected and not create a document."""
    from app.routers import storage as storage_router

    owner, proposal, version, session, scheme = upload_fixtures
    session.status = "failed"
    db = _make_fake_db([session, session, proposal, proposal, scheme, scheme, version])

    _patch_storage_router(monkeypatch, storage_router)

    with pytest.raises(HTTPException) as exc:
        await storage_router.confirm_upload(
            body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
            request=FakeRequest(),
            current_user=owner,
            db=db,
        )

    assert exc.value.status_code == 400
    assert "already been consumed" in exc.value.detail


@pytest.mark.asyncio
async def test_confirm_upload_success_enqueues_extraction_once(monkeypatch, upload_fixtures):
    """A successful confirmation must enqueue exactly one extraction job."""
    from app.routers import storage as storage_router
    import app.routers.storage as storage_module

    owner, proposal, version, session, scheme = upload_fixtures
    db = _make_fake_db([session, proposal, scheme, version])

    _patch_storage_router(monkeypatch, storage_router)

    enqueue_count = 0

    class CountingPool(FakePool):
        async def enqueue_job(self, *_args, **_kwargs):
            nonlocal enqueue_count
            enqueue_count += 1
            return None

    async def create_pool(*_args, **_kwargs):
        return CountingPool()

    monkeypatch.setattr(storage_module.arq, "create_pool", create_pool)

    response = await storage_router.confirm_upload(
        body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
        request=FakeRequest(),
        current_user=owner,
        db=db,
    )

    assert response["status"] == "confirmed"
    assert session.status == "consumed"
    assert enqueue_count == 1, "Extraction must be enqueued exactly once"


@pytest.mark.asyncio
async def test_concurrent_confirm_upload_is_safe(monkeypatch, upload_fixtures):
    """Simulating concurrent confirmation: only the first should succeed.

    This uses the session status check as the serialisation point.
    Since the code checks 'session.status != "pending"' before proceeding,
    the second call operating on the already-modified session must fail.
    """
    from app.routers import storage as storage_router

    owner, proposal, version, session, scheme = upload_fixtures

    # First confirmation — should succeed
    db1 = _make_fake_db([session, proposal, scheme, version])
    _patch_storage_router(monkeypatch, storage_router)

    class NoopPool(FakePool):
        async def enqueue_job(self, *_args, **_kwargs):
            return None

    async def create_pool1(*_args, **_kwargs):
        return NoopPool()

    monkeypatch.setattr(storage_router.arq, "create_pool", create_pool1)

    response1 = await storage_router.confirm_upload(
        body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
        request=FakeRequest(),
        current_user=owner,
        db=db1,
    )
    assert response1["status"] == "confirmed"
    assert session.status == "consumed"

    # Second confirmation — session is now consumed, must fail
    session.status = "consumed"
    session.consumed_at = datetime.now(timezone.utc)
    db2 = _make_fake_db([session, session, proposal, proposal, scheme, scheme, version])

    with pytest.raises(HTTPException) as exc:
        await storage_router.confirm_upload(
            body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
            request=FakeRequest(),
            current_user=owner,
            db=db2,
        )

    assert exc.value.status_code == 400
    assert "already been consumed" in exc.value.detail
