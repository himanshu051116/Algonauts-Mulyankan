"""Authorization and failure behaviour for private document downloads."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models.proposal import ProposalDocument, ProposalVersion
from app.models.user import User, UserRole


class Result:
    def __init__(self, value):
        self.value = value

    def one_or_none(self):
        return self.value


class FakeDb:
    def __init__(self, value):
        self.value = value

    async def execute(self, _statement):
        return Result(self.value)


class FakeRequest:
    client = type("Client", (), {"host": "127.0.0.1"})()
    headers = {"user-agent": "pytest"}


def _user() -> User:
    return User(
        id="owner-1",
        email="owner@example.gov.in",
        role=UserRole.APPLICANT,
        is_active=True,
        is_verified=True,
    )


@pytest.mark.asyncio
async def test_authorized_document_download_is_presigned_and_audited(monkeypatch):
    from app.routers import storage

    document = ProposalDocument(
        id="doc-1",
        proposal_version_id="version-1",
        file_name="proposal.pdf",
        file_type="pdf",
        file_size=100,
        storage_path="proposals/p1/v1/proposal.pdf",
        sha256_hash="0" * 64,
    )
    version = ProposalVersion(
        id="version-1", proposal_id="proposal-1", version_number=1
    )
    authorized = []
    audited = []

    async def allow(_db, _user, proposal_id, **_kwargs):
        authorized.append(proposal_id)

    async def sign(path, expires_in):
        assert path == document.storage_path
        assert expires_in > 0
        return "https://storage.example/signed"

    async def audit(*_args, **kwargs):
        audited.append(kwargs["event_type"])

    monkeypatch.setattr(storage, "get_proposal_for_user", allow)
    monkeypatch.setattr(storage, "get_signed_download_url", sign)
    monkeypatch.setattr(storage, "create_audit_event", audit)

    response = await storage.create_document_download_url(
        document_id=document.id,
        request=FakeRequest(),
        current_user=_user(),
        db=FakeDb((document, version)),
    )
    assert response.download_url == "https://storage.example/signed"
    assert authorized == ["proposal-1"]
    assert audited == ["document.download_url_created"]


@pytest.mark.asyncio
async def test_missing_document_is_concealed(monkeypatch):
    from app.routers import storage

    with pytest.raises(HTTPException) as exc:
        await storage.create_document_download_url(
            document_id="missing",
            request=FakeRequest(),
            current_user=_user(),
            db=FakeDb(None),
        )
    assert exc.value.status_code == 404
