from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.models.proposal import FundingScheme, Proposal, ProposalVersion, UploadSession
from app.models.user import User, UserRole


class Result:
    def __init__(self, item):
        self.item = item

    def scalar_one_or_none(self):
        return self.item


class FakeDb:
    def __init__(self, upload_session, proposal, scheme=None, version=None):
        self.upload_session = upload_session
        self.proposal = proposal
        self.scheme = scheme
        self.version = version
        self.commits = 0

    async def execute(self, _statement):
        if self.upload_session is not None:
            item = self.upload_session
            self.upload_session = None
            return Result(item)
        if self.proposal is not None:
            item = self.proposal
            self.proposal = None
            return Result(item)
        if self.scheme is not None:
            item = self.scheme
            self.scheme = None
            return Result(item)
        return Result(self.version)

    def add(self, _item):
        return None

    async def commit(self):
        self.commits += 1


@pytest.fixture
def upload_objects(tmp_path: Path):
    owner = User(id="user-1", email="owner@example.gov.in", role=UserRole.APPLICANT, is_active=True, is_verified=True)
    scheme = FundingScheme(id="scheme-1", code="MOC-ST", name="Ministry of Coal S&T", is_active=True)
    proposal = Proposal(id="proposal-1", owner_id=owner.id, scheme_id=scheme.id, title="Coal R&D", status="draft", current_version=1)
    version = ProposalVersion(id="version-1", proposal_id=proposal.id, version_number=1)
    upload_session = UploadSession(
        id="session-1",
        owner_id=owner.id,
        proposal_id=proposal.id,
        proposal_version_id=version.id,
        document_id="doc-1",
        storage_path="proposals/proposal-1/v1/doc-1_report.pdf",
        expected_file_name="report.pdf",
        allowed_content_types=["application/pdf"],
        maximum_size=1024 * 1024,
        expected_size=32,
        checksum=None,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    upload_session.proposal_version = version
    return owner, proposal, version, upload_session, scheme


@pytest.mark.asyncio
async def test_confirm_upload_rejects_wrong_owner(monkeypatch, upload_objects):
    from app.routers import storage as storage_router

    owner, proposal, _version, upload_session, scheme = upload_objects
    other_user = User(id="user-2", email="other@example.gov.in", role=UserRole.APPLICANT, is_active=True, is_verified=True)
    db = FakeDb(upload_session, proposal, scheme)

    async def head_object(*_args, **_kwargs):
        return {"ContentLength": 32, "ContentType": "application/pdf"}

    async def download_object_to_file(*_args, **_kwargs):
        return 32

    async def compute_file_hash(*_args, **_kwargs):
        return "f" * 64

    async def extract_pdf(*_args, **_kwargs):
        return {"text": "Coal proposal text", "warnings": []}

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

    with pytest.raises(HTTPException) as exc:
        await storage_router.confirm_upload(
            body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
            request=FakeRequest(),
            current_user=other_user,
            db=db,
        )

    assert exc.value.status_code == 403
    assert upload_session.status == "pending"


@pytest.mark.asyncio
async def test_confirm_upload_uses_server_loaded_session(monkeypatch, upload_objects):
    from app.routers import storage as storage_router

    owner, proposal, version, upload_session, scheme = upload_objects
    db = FakeDb(upload_session, proposal, scheme, version)

    async def head_object(*_args, **_kwargs):
        return {"ContentLength": 32, "ContentType": "application/pdf"}

    async def download_object_to_file(*_args, **_kwargs):
        assert _args[0] == "proposals/proposal-1/v1/doc-1_report.pdf"
        _args[1].write_bytes(b"%PDF-1.7\nfake pdf bytes")
        return 32

    async def compute_file_hash(*_args, **_kwargs):
        return "f" * 64

    async def extract_pdf(*_args, **_kwargs):
        return {"text": "Coal proposal text", "warnings": []}

    async def extract_structured_fields(*_args, **_kwargs):
        return [{"field_name": "project_duration", "field_value": "24"}]

    async def create_audit_event(*_args, **_kwargs):
        return None

    monkeypatch.setattr(storage_router, "head_object", head_object)
    monkeypatch.setattr(storage_router, "download_object_to_file", download_object_to_file)
    monkeypatch.setattr(storage_router, "compute_file_hash", compute_file_hash)
    monkeypatch.setattr(storage_router, "extract_pdf", extract_pdf)
    monkeypatch.setattr(storage_router, "extract_structured_fields", extract_structured_fields)
    monkeypatch.setattr(storage_router, "create_audit_event", create_audit_event)

    class FakePool:
        async def enqueue_job(self, *_args, **_kwargs):
            return None

        async def close(self):
            return None

    async def create_pool(*_args, **_kwargs):
        return FakePool()

    monkeypatch.setattr(storage_router.arq, "create_pool", create_pool)

    class FakeRequest:
        client = type("Client", (), {"host": "127.0.0.1"})()
        headers = {"user-agent": "pytest"}

    response = await storage_router.confirm_upload(
        body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
        request=FakeRequest(),
        current_user=owner,
        db=db,
    )

    assert response["document_id"] == "doc-1"
    assert response["status"] == "confirmed"
    assert response["extraction_status"] == "complete"
    assert upload_session.status == "consumed"


@pytest.mark.asyncio
async def test_confirm_upload_rejects_expired_session(monkeypatch, upload_objects):
    from app.routers import storage as storage_router

    owner, proposal, _version, upload_session, scheme = upload_objects
    upload_session.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db = FakeDb(upload_session, proposal, scheme)

    async def create_durable_audit_event(*_args, **_kwargs):
        return None

    monkeypatch.setattr(storage_router, "create_durable_audit_event", create_durable_audit_event)

    class FakeRequest:
        client = type("Client", (), {"host": "127.0.0.1"})()
        headers = {"user-agent": "pytest"}

    with pytest.raises(HTTPException) as exc:
        await storage_router.confirm_upload(
            body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
            request=FakeRequest(),
            current_user=owner,
            db=db,
        )

    assert exc.value.status_code == 400
    assert upload_session.status == "expired"


@pytest.mark.asyncio
async def test_confirm_upload_rejects_oversized_file(monkeypatch, upload_objects):
    from app.routers import storage as storage_router

    owner, proposal, _version, upload_session, scheme = upload_objects
    db = FakeDb(upload_session, proposal, scheme)

    async def head_object(*_args, **_kwargs):
        return {"ContentLength": upload_session.maximum_size + 1, "ContentType": "application/pdf"}

    async def create_durable_audit_event(*_args, **_kwargs):
        return None

    monkeypatch.setattr(storage_router, "head_object", head_object)
    monkeypatch.setattr(storage_router, "create_durable_audit_event", create_durable_audit_event)

    class FakeRequest:
        client = type("Client", (), {"host": "127.0.0.1"})()
        headers = {"user-agent": "pytest"}

    with pytest.raises(HTTPException) as exc:
        await storage_router.confirm_upload(
            body=storage_router.UploadConfirmRequest(upload_session_id="session-1"),
            request=FakeRequest(),
            current_user=owner,
            db=db,
        )

    assert exc.value.status_code == 400
