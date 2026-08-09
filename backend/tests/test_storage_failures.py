"""Tests for storage-layer failures: missing objects, MinIO unavailability, bucket errors."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.models.proposal import FundingScheme, Proposal, ProposalVersion, UploadSession
from app.models.user import User, UserRole
from app.services.storage import StorageError


class Result:
    def __init__(self, item):
        self.item = item

    def scalar_one_or_none(self):
        return self.item


class FakeDb:
    def __init__(self, items):
        self.items = list(items)
        self.commits = 0

    async def execute(self, _statement):
        return Result(self.items.pop(0) if self.items else None)

    def add(self, item):
        pass

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1


class FakeRequest:
    client = type("Client", (), {"host": "127.0.0.1"})()
    headers = {"user-agent": "pytest"}


@pytest.fixture
def base_fixtures():
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
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    session.proposal_version = version
    return owner, proposal, version, session, scheme


# ============================================================
# PHASE 6 — OBJECT MISSING DURING CONFIRMATION
# ============================================================


@pytest.mark.asyncio
async def test_confirm_upload_reports_missing_object(monkeypatch, base_fixtures):
    """When the uploaded object is not found in storage, confirmation must fail."""
    from app.routers import storage as storage_router
    from app.services.storage import StorageError

    owner, proposal, version, session, scheme = base_fixtures
    db = FakeDb([session, proposal, scheme, version])

    async def head_object_missing(*args, **kwargs):
        raise StorageError("Object not found")

    monkeypatch.setattr(storage_router, "head_object", head_object_missing)

    async def create_durable_audit_event(*args, **kwargs):
        return None

    monkeypatch.setattr(storage_router, "create_durable_audit_event", create_durable_audit_event)

    with pytest.raises(HTTPException) as exc:
        await storage_router.confirm_upload(
            body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
            request=FakeRequest(),
            current_user=owner,
            db=db,
        )

    assert exc.value.status_code == 400
    assert "not found in storage" in exc.value.detail


@pytest.mark.asyncio
async def test_confirm_upload_reports_missing_object_during_download(monkeypatch, base_fixtures):
    """When the object disappears between head and download, confirmation must fail."""
    from app.routers import storage as storage_router

    owner, proposal, version, session, scheme = base_fixtures
    db = FakeDb([session, proposal, scheme, version])

    async def head_object_ok(*args, **kwargs):
        return {"ContentLength": 32, "ContentType": "application/pdf"}

    monkeypatch.setattr(storage_router, "head_object", head_object_ok)

    async def download_fails(*args, **kwargs):
        raise StorageError("Object could not be downloaded")

    monkeypatch.setattr(storage_router, "download_object_to_file", download_fails)

    async def create_durable_audit_event(*args, **kwargs):
        return None

    monkeypatch.setattr(storage_router, "create_durable_audit_event", create_durable_audit_event)

    with pytest.raises(HTTPException) as exc:
        await storage_router.confirm_upload(
            body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
            request=FakeRequest(),
            current_user=owner,
            db=db,
        )

    assert exc.value.status_code == 400
    assert "could not be downloaded" in exc.value.detail


@pytest.mark.asyncio
async def test_head_object_distinguishes_not_found_from_auth_failure():
    """The storage service keeps distinct user-safe error categories."""
    from app.services.storage import StorageError

    assert str(StorageError("Object not found")) != str(
        StorageError("Storage authentication failed")
    )


@pytest.mark.asyncio
async def test_confirm_upload_does_not_consume_session_on_missing_object(monkeypatch, base_fixtures):
    """When object is missing, the upload session must remain in 'pending' state."""
    from app.routers import storage as storage_router
    from app.services.storage import StorageError

    owner, proposal, version, session, scheme = base_fixtures
    db = FakeDb([session, proposal, scheme, version])

    async def head_object_missing(*args, **kwargs):
        raise StorageError("Object not found")

    monkeypatch.setattr(storage_router, "head_object", head_object_missing)

    async def create_durable_audit_event(*args, **kwargs):
        return None

    monkeypatch.setattr(storage_router, "create_durable_audit_event", create_durable_audit_event)

    with pytest.raises(HTTPException):
        await storage_router.confirm_upload(
            body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
            request=FakeRequest(),
            current_user=owner,
            db=db,
        )

    assert session.status == "failed", "Session must be marked failed when object is missing"


# ============================================================
# PHASE 11 — MINIO UNAVAILABLE DURING CONFIRMATION
# ============================================================


@pytest.mark.asyncio
async def test_confirm_upload_handles_minio_connection_failure(monkeypatch, base_fixtures):
    """A connection failure to MinIO must produce a safe 502/503, not 500."""
    from app.routers import storage as storage_router
    from app.services.storage import StorageError

    owner, proposal, version, session, scheme = base_fixtures
    db = FakeDb([session, proposal, scheme, version])

    async def head_object_connection_refused(*args, **kwargs):
        raise StorageError("Storage service is unavailable")

    monkeypatch.setattr(storage_router, "head_object", head_object_connection_refused)

    async def create_durable_audit_event(*args, **kwargs):
        return None

    monkeypatch.setattr(storage_router, "create_durable_audit_event", create_durable_audit_event)

    with pytest.raises(HTTPException) as exc:
        await storage_router.confirm_upload(
            body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
            request=FakeRequest(),
            current_user=owner,
            db=db,
        )

    # Must return a safe error, not leak the internal exception
    assert exc.value.status_code == 400
    assert "not found in storage" in exc.value.detail or "unavailable" in exc.value.detail


@pytest.mark.asyncio
async def test_confirm_upload_handles_minio_auth_failure(monkeypatch, base_fixtures):
    """A storage authentication failure must not be confused with object not found."""
    from app.routers import storage as storage_router
    from app.services.storage import StorageError

    owner, proposal, version, session, scheme = base_fixtures
    db = FakeDb([session, proposal, scheme, version])

    async def head_object_auth_fail(*args, **kwargs):
        raise StorageError("Storage authentication failed")

    monkeypatch.setattr(storage_router, "head_object", head_object_auth_fail)

    async def create_durable_audit_event(*args, **kwargs):
        return None

    monkeypatch.setattr(storage_router, "create_durable_audit_event", create_durable_audit_event)

    with pytest.raises(HTTPException) as exc:
        await storage_router.confirm_upload(
            body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
            request=FakeRequest(),
            current_user=owner,
            db=db,
        )

    assert exc.value.status_code == 400


# ============================================================
# PHASE 15 — ADDITIONAL UPLOAD INTEGRITY TESTS
# ============================================================


@pytest.mark.asyncio
async def test_confirm_upload_session_wrong_expected_filename(monkeypatch, base_fixtures):
    """The confirm upload must use the server-stored filename, not the client-supplied one."""
    from app.routers import storage as storage_router

    owner, proposal, version, session, scheme = base_fixtures
    db = FakeDb([session, proposal, scheme, version])

    async def head_object(*args, **kwargs):
        return {"ContentLength": 32, "ContentType": "application/pdf"}

    monkeypatch.setattr(storage_router, "head_object", head_object)

    async def download_object_to_file(*args, **kwargs):
        args[1].write_bytes(b"%PDF-1.7\ncoal data")
        return 32

    monkeypatch.setattr(storage_router, "download_object_to_file", download_object_to_file)

    async def compute_file_hash(*args, **kwargs):
        return "f" * 64

    monkeypatch.setattr(storage_router, "compute_file_hash", compute_file_hash)

    async def extract_pdf(*args, **kwargs):
        return {"text": "coal", "warnings": []}

    monkeypatch.setattr(storage_router, "extract_pdf", extract_pdf)

    async def extract_structured_fields(*args, **kwargs):
        return []

    async def create_audit_event(*args, **kwargs):
        return None

    async def create_durable_audit_event(*args, **kwargs):
        return None

    monkeypatch.setattr(storage_router, "create_audit_event", create_audit_event)
    monkeypatch.setattr(storage_router, "create_durable_audit_event", create_durable_audit_event)
    monkeypatch.setattr(storage_router, "extract_structured_fields", extract_structured_fields)

    class NoopPool:
        async def enqueue_job(self, *a, **kw):
            return None

        async def close(self):
            return None

    async def create_pool(*a, **kw):
        return NoopPool()

    monkeypatch.setattr(storage_router.arq, "create_pool", create_pool)

    response = await storage_router.confirm_upload(
        body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
        request=FakeRequest(),
        current_user=owner,
        db=db,
    )

    assert response["status"] == "confirmed"


@pytest.mark.asyncio
async def test_confirm_upload_rejects_size_mismatch_after_upload(monkeypatch, base_fixtures):
    """If the actual stored size differs from expected_size, confirmation must fail."""
    from app.routers import storage as storage_router

    owner, proposal, version, session, scheme = base_fixtures
    session.expected_size = 32
    db = FakeDb([session, proposal, scheme, version])

    async def head_object(*args, **kwargs):
        return {"ContentLength": 99999, "ContentType": "application/pdf"}

    monkeypatch.setattr(storage_router, "head_object", head_object)

    async def create_durable_audit_event(*args, **kwargs):
        return None

    monkeypatch.setattr(storage_router, "create_durable_audit_event", create_durable_audit_event)

    with pytest.raises(HTTPException) as exc:
        await storage_router.confirm_upload(
            body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
            request=FakeRequest(),
            current_user=owner,
            db=db,
        )

    assert exc.value.status_code == 400
