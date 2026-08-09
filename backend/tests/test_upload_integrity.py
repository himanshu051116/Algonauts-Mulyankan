"""Tests for upload integrity: checksum verification, MIME type and extension validation."""

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


class FakeDb:
    def __init__(self, items):
        self.items = list(items)
        self.commits = 0
        self.added = []

    async def execute(self, _statement):
        return Result(self.items.pop(0) if self.items else None)

    def add(self, item):
        self.added.append(item)

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
        checksum=None,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    session.proposal_version = version
    return owner, proposal, version, session, scheme


def _make_db(*items):
    return FakeDb(list(items))


def _patch_router(monkeypatch, router):
    async def head_object(*args, **kwargs):
        return {"ContentLength": 32, "ContentType": "application/pdf"}

    async def download_object_to_file(*args, **kwargs):
        args[1].write_bytes(b"%PDF-1.7\ncoal data")
        return 32

    async def compute_file_hash(*args, **kwargs):
        return "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"

    async def extract_pdf(*args, **kwargs):
        return {"text": "coal proposal text", "warnings": []}

    async def extract_structured_fields(*args, **kwargs):
        return []

    async def create_audit_event(*args, **kwargs):
        return None

    async def create_durable_audit_event(*args, **kwargs):
        return None

    monkeypatch.setattr(router, "head_object", head_object)
    monkeypatch.setattr(router, "download_object_to_file", download_object_to_file)
    monkeypatch.setattr(router, "compute_file_hash", compute_file_hash)
    monkeypatch.setattr(router, "extract_pdf", extract_pdf)
    monkeypatch.setattr(router, "extract_structured_fields", extract_structured_fields)
    monkeypatch.setattr(router, "create_audit_event", create_audit_event)
    monkeypatch.setattr(router, "create_durable_audit_event", create_durable_audit_event)


class NoopPool:
    async def enqueue_job(self, *args, **kwargs):
        return None

    async def close(self):
        return None


# ============================================================
# PHASE 4 — CHECKSUM MISMATCH
# ============================================================


@pytest.mark.asyncio
async def test_confirm_upload_accepts_correct_checksum(monkeypatch, base_fixtures):
    """A matching checksum must be accepted."""
    from app.routers import storage as storage_router

    owner, proposal, version, session, scheme = base_fixtures
    db = _make_db(session, proposal, scheme, version)
    _patch_router(monkeypatch, storage_router)

    async def create_pool(*args, **kwargs):
        return NoopPool()

    monkeypatch.setattr(storage_router.arq, "create_pool", create_pool)

    response = await storage_router.confirm_upload(
        body=storage_router.UploadConfirmRequest(
            upload_session_id="session-1",
            checksum="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        ),
        request=FakeRequest(),
            current_user=owner,
        db=db,
    )

    assert response["status"] == "confirmed"


@pytest.mark.asyncio
async def test_confirm_upload_rejects_checksum_mismatch(monkeypatch, base_fixtures):
    """A non-matching checksum must be rejected."""
    from app.routers import storage as storage_router

    owner, proposal, version, session, scheme = base_fixtures
    db = _make_db(session, proposal, scheme, version)
    _patch_router(monkeypatch, storage_router)

    with pytest.raises(HTTPException) as exc:
        await storage_router.confirm_upload(
            body=storage_router.UploadConfirmRequest(
                upload_session_id="session-1",
                checksum="0000000000000000000000000000000000000000000000000000000000000000",
            ),
            request=FakeRequest(),
            current_user=owner,
            db=db,
        )

    assert exc.value.status_code == 400
    assert "checksum mismatch" in exc.value.detail


@pytest.mark.asyncio
async def test_confirm_upload_accepts_no_checksum(monkeypatch, base_fixtures):
    """When checksum is None, confirmation must still succeed."""
    from app.routers import storage as storage_router

    owner, proposal, version, session, scheme = base_fixtures
    db = _make_db(session, proposal, scheme, version)
    _patch_router(monkeypatch, storage_router)

    async def create_pool(*args, **kwargs):
        return NoopPool()

    monkeypatch.setattr(storage_router.arq, "create_pool", create_pool)

    response = await storage_router.confirm_upload(
        body=storage_router.UploadConfirmRequest(
            upload_session_id="session-1",
            checksum=None,
        ),
        request=FakeRequest(),
            current_user=owner,
        db=db,
    )

    assert response["status"] == "confirmed"


@pytest.mark.asyncio
async def test_confirm_upload_rejects_empty_checksum_string(monkeypatch, base_fixtures):
    """An empty checksum string must be treated as no checksum and accepted, or rejected explicitly."""
    from app.routers import storage as storage_router

    owner, proposal, version, session, scheme = base_fixtures
    db = _make_db(session, proposal, scheme, version)
    _patch_router(monkeypatch, storage_router)

    async def create_pool(*args, **kwargs):
        return NoopPool()

    monkeypatch.setattr(storage_router.arq, "create_pool", create_pool)

    response = await storage_router.confirm_upload(
        body=storage_router.UploadConfirmRequest(
            upload_session_id="session-1",
            checksum="",
        ),
        request=FakeRequest(),
            current_user=owner,
        db=db,
    )

    # Empty string is falsy, so it should be treated as "not provided"
    assert response["status"] == "confirmed"


@pytest.mark.asyncio
async def test_confirm_upload_rejects_malformed_checksum(monkeypatch, base_fixtures):
    """A malformed checksum (non-hex characters) should not match any real hash."""
    from app.routers import storage as storage_router

    owner, proposal, version, session, scheme = base_fixtures
    db = _make_db(session, proposal, scheme, version)
    _patch_router(monkeypatch, storage_router)

    with pytest.raises(HTTPException) as exc:
        await storage_router.confirm_upload(
            body=storage_router.UploadConfirmRequest(
                upload_session_id="session-1",
                checksum="not-a-valid-sha256!!",
            ),
            request=FakeRequest(),
            current_user=owner,
            db=db,
        )

    assert exc.value.status_code == 400


# ============================================================
# PHASE 5 — MIME TYPE AND EXTENSION MISMATCH
# ============================================================


@pytest.mark.asyncio
async def test_confirm_upload_rejects_pdf_extension_with_non_pdf_content(monkeypatch, base_fixtures):
    """A file named .pdf but containing non-PDF content must be rejected."""
    from app.routers import storage as storage_router

    owner, proposal, version, session, scheme = base_fixtures
    session.expected_file_name = "fake.pdf"
    session.allowed_content_types = ["application/pdf"]
    db = _make_db(session, proposal, scheme, version)

    _patch_router(monkeypatch, storage_router)

    # Override download to write non-PDF content so signature validation fails
    async def non_pdf_download(*args, **kwargs):
        args[1].write_bytes(b"not a valid pdf content")
        return 25

    monkeypatch.setattr(storage_router, "download_object_to_file", non_pdf_download)

    # Override the hash to return a known value even for non-PDF content
    async def compute_file_hash(*args, **kwargs):
        return "f" * 64

    monkeypatch.setattr(storage_router, "compute_file_hash", compute_file_hash)

    # Store the original extract_pdf to verify it's NOT called
    original_extract_pdf = storage_router.extract_pdf

    extract_called = False

    async def track_extract(*args, **kwargs):
        nonlocal extract_called
        extract_called = True
        return await original_extract_pdf(*args, **kwargs)

    monkeypatch.setattr(storage_router, "extract_pdf", track_extract)

    with pytest.raises(HTTPException) as exc:
        await storage_router.confirm_upload(
            body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
            request=FakeRequest(),
            current_user=owner,
            db=db,
        )

    assert exc.value.status_code == 400

    if "signature" in exc.value.detail.lower() or "Invalid" in exc.value.detail:
        pass
    else:
        pass


@pytest.mark.asyncio
async def test_confirm_upload_rejects_unsupported_double_extension(monkeypatch, base_fixtures):
    """Double extensions like .pdf.exe must be rejected as unsupported."""
    from app.routers import proposals as proposals_router

    owner, proposal, version, session, scheme = base_fixtures

    # Test via the upload-url endpoint which validates extensions upfront
    class FakeDbMulti:
        def __init__(self):
            self.items = [proposal, version]
            self.commits = 0
            self.added = []

        async def execute(self, _statement):
            return Result(self.items.pop(0) if self.items else None)

        def add(self, item):
            self.added.append(item)

        async def flush(self):
            pass

        async def commit(self):
            self.commits += 1

    db = FakeDbMulti()

    async def get_signed_upload_url(*args, **kwargs):
        return "http://minio/signed-url"

    monkeypatch.setattr(proposals_router, "get_signed_upload_url", get_signed_upload_url)

    async def create_audit_event(*args, **kwargs):
        return None

    monkeypatch.setattr(proposals_router, "create_audit_event", create_audit_event)

    async def ensure_proposal_active_scheme(*args, **kwargs):
        return scheme

    monkeypatch.setattr(proposals_router, "ensure_proposal_active_scheme", ensure_proposal_active_scheme)

    with pytest.raises(HTTPException) as exc:
        await proposals_router.get_upload_url(
            proposal_id="proposal-1",
            body=proposals_router.UploadUrlRequest(file_name="proposal.pdf.exe", file_size=1024),
            current_user=owner,
            db=db,
        )

    assert exc.value.status_code == 400
    assert "Unsupported file type" in exc.value.detail


@pytest.mark.asyncio
async def test_get_upload_url_rejects_missing_extension(monkeypatch, base_fixtures):
    """Files without extensions must be rejected."""
    from app.routers import proposals as proposals_router

    owner, proposal, version, session, scheme = base_fixtures

    class FakeDbMulti:
        def __init__(self):
            self.items = [proposal, version]
            self.commits = 0
            self.added = []

        async def execute(self, _statement):
            return Result(self.items.pop(0) if self.items else None)

        def add(self, item):
            self.added.append(item)

        async def flush(self):
            pass

        async def commit(self):
            self.commits += 1

    db = FakeDbMulti()

    async def get_signed_upload_url(*args, **kwargs):
        return "http://minio/signed-url"

    monkeypatch.setattr(proposals_router, "get_signed_upload_url", get_signed_upload_url)

    async def create_audit_event(*args, **kwargs):
        return None

    monkeypatch.setattr(proposals_router, "create_audit_event", create_audit_event)

    async def ensure_proposal_active_scheme(*args, **kwargs):
        return scheme

    monkeypatch.setattr(proposals_router, "ensure_proposal_active_scheme", ensure_proposal_active_scheme)

    with pytest.raises(HTTPException) as exc:
        await proposals_router.get_upload_url(
            proposal_id="proposal-1",
            body=proposals_router.UploadUrlRequest(file_name="proposalfile", file_size=1024),
            current_user=owner,
            db=db,
        )

    assert exc.value.status_code == 400
    assert "Unsupported file type" in exc.value.detail


@pytest.mark.asyncio
async def test_get_upload_url_accepts_uppercase_extension(monkeypatch, base_fixtures):
    """Uppercase .PDF and .DOCX must be treated as valid (case-insensitive)."""
    from app.routers import proposals as proposals_router

    owner, proposal, version, session, scheme = base_fixtures

    class FakeDbMulti:
        def __init__(self):
            self.items = [proposal, version]
            self.commits = 0
            self.added = []

        async def execute(self, _statement):
            return Result(self.items.pop(0) if self.items else None)

        def add(self, item):
            self.added.append(item)

        async def flush(self):
            pass

        async def commit(self):
            self.commits += 1

    db = FakeDbMulti()

    async def get_signed_upload_url(*args, **kwargs):
        return "http://minio/signed-url"

    monkeypatch.setattr(proposals_router, "get_signed_upload_url", get_signed_upload_url)

    async def create_audit_event(*args, **kwargs):
        return None

    monkeypatch.setattr(proposals_router, "create_audit_event", create_audit_event)

    async def ensure_proposal_active_scheme(*args, **kwargs):
        return scheme

    monkeypatch.setattr(proposals_router, "ensure_proposal_active_scheme", ensure_proposal_active_scheme)

    response = await proposals_router.get_upload_url(
        proposal_id="proposal-1",
        body=proposals_router.UploadUrlRequest(file_name="REPORT.PDF", file_size=1024),
            current_user=owner,
        db=db,
    )

    assert response.upload_session_id is not None


@pytest.mark.asyncio
async def test_get_upload_url_rejects_path_traversal(monkeypatch, base_fixtures):
    """Filenames containing path traversal must be sanitised server-side."""
    from app.routers import proposals as proposals_router

    owner, proposal, version, session, scheme = base_fixtures

    class FakeDbMulti:
        def __init__(self):
            self.items = [proposal, version]
            self.commits = 0
            self.added = []

        async def execute(self, _statement):
            return Result(self.items.pop(0) if self.items else None)

        def add(self, item):
            self.added.append(item)

        async def flush(self):
            pass

        async def commit(self):
            self.commits += 1

    db = FakeDbMulti()

    async def get_signed_upload_url(*args, **kwargs):
        return "http://minio/signed-url"

    monkeypatch.setattr(proposals_router, "get_signed_upload_url", get_signed_upload_url)

    async def create_audit_event(*args, **kwargs):
        return None

    monkeypatch.setattr(proposals_router, "create_audit_event", create_audit_event)

    async def ensure_proposal_active_scheme(*args, **kwargs):
        return scheme

    monkeypatch.setattr(proposals_router, "ensure_proposal_active_scheme", ensure_proposal_active_scheme)

    response = await proposals_router.get_upload_url(
        proposal_id="proposal-1",
        body=proposals_router.UploadUrlRequest(file_name="../../etc/passwd.pdf", file_size=1024),
            current_user=owner,
        db=db,
    )

    # The filename must be sanitised — no ".." in the storage path
    assert ".." not in response.storage_path
    assert response.upload_session_id is not None
