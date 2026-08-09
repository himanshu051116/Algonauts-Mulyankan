"""
Storage router: upload confirmation and document processing.

The client confirms only an upload-session identifier. File name, object key,
proposal/version/document ids, size limits, and allowed types are loaded from
the database.
"""

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile

import arq
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.config import settings
from app.database import get_db
from app.models.proposal import (
    DocumentPage,
    ExtractedField,
    Proposal,
    ProposalDocument,
    ProposalVersion,
    UploadSession,
)
from app.models.user import User, UserRole
from app.schemas.proposal import (
    DocumentDownloadResponse,
    ExtractedFieldCorrectionRequest,
    ExtractedFieldListResponse,
    ExtractedFieldResponse,
    UploadConfirmRequest,
)
from app.services.access import enforce_shadow_review_blindness, get_proposal_for_user
from app.services.audit import create_audit_event, create_durable_audit_event
from app.services.field_schema import canonicalize_extracted_fields
from app.services.document import (
    compute_file_hash,
    extract_docx,
    extract_pdf,
    extract_structured_fields,
)
from app.services.malware import MalwareScanError, scan_file
from app.services.schemes import ensure_proposal_active_scheme
from app.services.storage import (
    StorageError,
    download_object_to_file,
    get_signed_download_url,
    head_object,
)

router = APIRouter()

CONTENT_TYPES_BY_EXTENSION = {
    ".pdf": {"application/pdf"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    },
    ".txt": {"text/plain"},
}


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _normalise_content_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def _validate_mime_and_extension(
    file_name: str, content_type: str, allowed: list[str]
) -> str:
    extension = Path(file_name).suffix.lower()
    expected_for_extension = CONTENT_TYPES_BY_EXTENSION.get(extension)
    if not expected_for_extension:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    normalised_type = _normalise_content_type(content_type)
    if (
        normalised_type not in set(allowed)
        or normalised_type not in expected_for_extension
    ):
        raise HTTPException(
            status_code=400, detail="Object content type does not match upload session"
        )
    return extension


def _validate_file_signature(path: Path, extension: str) -> None:
    signature = path.read_bytes()[:8]
    if extension == ".pdf" and not signature.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Invalid PDF file signature")
    if extension == ".docx" and not signature.startswith(b"PK\x03\x04"):
        raise HTTPException(status_code=400, detail="Invalid DOCX file signature")
    if extension == ".txt" and b"\x00" in signature:
        raise HTTPException(status_code=400, detail="Invalid text file signature")


async def _record_extraction_failure(
    upload_session_id: str,
    proposal_id: str,
    document_id: str,
    current_user: User,
    request: Request,
    reason: str,
    status_code: int | None = None,
) -> None:
    await create_durable_audit_event(
        event_type="extraction.failed",
        user_id=current_user.id,
        resource_type="upload_session",
        resource_id=upload_session_id,
        details={
            "proposal_id": proposal_id,
            "document_id": document_id,
            "reason": reason,
            "status_code": status_code,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )




def _field_response(field: ExtractedField) -> ExtractedFieldResponse:
    effective = (
        field.manually_corrected_value
        if field.manually_corrected_value is not None
        else field.normalized_value or field.field_value
    )
    return ExtractedFieldResponse(
        field_name=field.field_name,
        extracted_value=field.field_value,
        normalized_value=field.normalized_value,
        manually_corrected_value=field.manually_corrected_value,
        effective_value=effective,
        original_text=field.original_text,
        source_page=field.source_page,
        source_section=field.source_section,
        char_start=field.char_start,
        char_end=field.char_end,
        evidence_coverage=field.evidence_coverage,
        validation_warnings=list(field.validation_warnings or []),
        conflict_status=field.conflict_status,
        corrected_by=field.corrected_by,
        corrected_at=field.corrected_at,
    )


def _corrected_content_hash(document_hash: str, structured_data: dict) -> str:
    payload = json.dumps(
        {"document_hash": document_hash, "structured_data": structured_data},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def _document_context(
    db: AsyncSession,
    document_id: str,
) -> tuple[ProposalDocument, ProposalVersion, Proposal]:
    result = await db.execute(
        select(ProposalDocument, ProposalVersion, Proposal)
        .join(
            ProposalVersion,
            ProposalVersion.id == ProposalDocument.proposal_version_id,
        )
        .join(Proposal, Proposal.id == ProposalVersion.proposal_id)
        .where(ProposalDocument.id == document_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return row[0], row[1], row[2]


@router.get(
    "/documents/{document_id}/fields",
    response_model=ExtractedFieldListResponse,
)
async def list_extracted_fields(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExtractedFieldListResponse:
    document, version, _proposal = await _document_context(db, document_id)
    await get_proposal_for_user(
        db, current_user, version.proposal_id, conceal_existence=True
    )
    await enforce_shadow_review_blindness(
        db,
        current_user,
        version.proposal_id,
        detail=(
            "Machine-extracted fields are hidden until the blind expert review is "
            "submitted; review the source documents directly"
        ),
    )
    result = await db.execute(
        select(ExtractedField)
        .where(ExtractedField.document_id == document.id)
        .order_by(ExtractedField.field_name.asc())
    )
    return ExtractedFieldListResponse(
        document_id=document.id,
        fields=[_field_response(field) for field in result.scalars().all()],
    )


@router.patch(
    "/documents/{document_id}/fields/{field_name}",
    response_model=ExtractedFieldResponse,
)
async def correct_extracted_field(
    document_id: str,
    field_name: str,
    body: ExtractedFieldCorrectionRequest,
    request: Request,
    current_user: User = Depends(
        require_role(UserRole.SCRUTINY_OFFICER, UserRole.ADMINISTRATOR)
    ),
    db: AsyncSession = Depends(get_db),
) -> ExtractedFieldResponse:
    document, version, proposal = await _document_context(db, document_id)
    if not document.is_primary or document.superseded_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Only the active primary document can be corrected",
        )
    if proposal.status in {"approved", "rejected", "withdrawn"}:
        raise HTTPException(
            status_code=409,
            detail="Finalised proposal evidence cannot be changed",
        )
    result = await db.execute(
        select(ExtractedField).where(
            ExtractedField.document_id == document.id,
            ExtractedField.field_name == field_name,
        )
    )
    field = result.scalar_one_or_none()
    if field is None:
        raise HTTPException(status_code=404, detail="Extracted field not found")

    previous_value = (
        field.manually_corrected_value
        if field.manually_corrected_value is not None
        else field.normalized_value or field.field_value
    )
    now = datetime.now(timezone.utc)
    field.manually_corrected_value = body.value
    field.corrected_by = current_user.id
    field.corrected_at = now
    field.conflict_status = "corrected"

    structured = copy.deepcopy(version.structured_data or {})
    fields = structured.setdefault("fields", {})
    entry = fields.setdefault(field.field_name, {})
    if not isinstance(entry, dict):
        entry = {}
        fields[field.field_name] = entry
    entry.update(
        {
            "normalized_value": body.value,
            "status": "manually_corrected",
            "manually_corrected": True,
            "corrected_by": current_user.id,
            "corrected_at": now.isoformat(),
            "correction_reason": body.reason,
        }
    )
    version.structured_data = structured
    version.content_hash = _corrected_content_hash(version.document_hash, structured)

    await create_audit_event(
        db,
        event_type="extraction.field_corrected",
        user=current_user,
        resource_type="extracted_field",
        resource_id=field.id,
        details={
            "proposal_id": proposal.id,
            "proposal_version_id": version.id,
            "document_id": document.id,
            "field_name": field.field_name,
            "previous_value": previous_value,
            "corrected_value": body.value,
            "reason": body.reason,
            "content_hash": version.content_hash,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    await db.refresh(field)
    return _field_response(field)


@router.get(
    "/documents/{document_id}/download-url",
    response_model=DocumentDownloadResponse,
)
async def create_document_download_url(
    document_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentDownloadResponse:
    result = await db.execute(
        select(ProposalDocument, ProposalVersion)
        .join(
            ProposalVersion,
            ProposalVersion.id == ProposalDocument.proposal_version_id,
        )
        .where(ProposalDocument.id == document_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    document, version = row
    await get_proposal_for_user(
        db, current_user, version.proposal_id, conceal_existence=True
    )
    try:
        download_url = await get_signed_download_url(
            document.storage_path,
            expires_in=settings.signed_download_ttl_seconds,
        )
    except StorageError as exc:
        raise HTTPException(
            status_code=503, detail="Document download is temporarily unavailable"
        ) from exc

    await create_audit_event(
        db,
        event_type="document.download_url_created",
        user=current_user,
        resource_type="proposal_document",
        resource_id=document.id,
        details={
            "proposal_id": version.proposal_id,
            "proposal_version_id": version.id,
            "expires_in": settings.signed_download_ttl_seconds,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return DocumentDownloadResponse(
        document_id=document.id,
        file_name=document.file_name,
        download_url=download_url,
        expires_in=settings.signed_download_ttl_seconds,
    )


@router.post("/confirm-upload")
async def confirm_upload(
    body: UploadConfirmRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm upload completion and trigger server-side extraction."""
    failure_audited = False
    session_owned_by_current_user = False
    try:
        session_result = await db.execute(
            select(UploadSession).where(UploadSession.id == body.upload_session_id)
        )
        upload_session = session_result.scalar_one_or_none()
        if not upload_session:
            raise HTTPException(status_code=404, detail="Upload session not found")
        if upload_session.owner_id != current_user.id:
            raise HTTPException(
                status_code=403, detail="Upload session does not belong to current user"
            )
        session_owned_by_current_user = True
        if upload_session.status != "pending" or upload_session.consumed_at is not None:
            raise HTTPException(
                status_code=400, detail="Upload session has already been consumed"
            )
        if _as_aware(upload_session.expires_at) <= datetime.now(timezone.utc):
            upload_session.status = "expired"
            await db.commit()
            raise HTTPException(status_code=400, detail="Upload session has expired")

        proposal_result = await db.execute(
            select(Proposal).where(
                Proposal.id == upload_session.proposal_id,
                Proposal.owner_id == current_user.id,
            )
        )
        proposal = proposal_result.scalar_one_or_none()
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")
        if proposal.status not in ("draft", "revision_required"):
            raise HTTPException(
                status_code=400, detail="Cannot upload to a non-draft proposal"
            )
        await ensure_proposal_active_scheme(db, proposal)

        try:
            object_head = await head_object(upload_session.storage_path)
        except StorageError as exc:
            raise HTTPException(
                status_code=400, detail="Uploaded object was not found in storage"
            ) from exc
        actual_size = int(object_head.get("ContentLength") or 0)
        if actual_size <= 0 or actual_size > upload_session.maximum_size:
            raise HTTPException(
                status_code=400,
                detail="Uploaded object size is outside the permitted limit",
            )
        if (
            upload_session.expected_size is not None
            and actual_size != upload_session.expected_size
        ):
            raise HTTPException(
                status_code=400,
                detail="Uploaded object size does not match upload session",
            )

        extension = _validate_mime_and_extension(
            upload_session.expected_file_name,
            str(object_head.get("ContentType") or ""),
            upload_session.allowed_content_types,
        )

        await create_audit_event(
            db,
            event_type="extraction.started",
            user=current_user,
            resource_type="upload_session",
            resource_id=upload_session.id,
            details={
                "proposal_id": upload_session.proposal_id,
                "document_id": upload_session.document_id,
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

        extracted_text = ""
        extraction_warnings = []
        file_hash = ""
        malware_scan_result = "not_scanned"

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / f"upload{extension}"
            try:
                downloaded_size = await download_object_to_file(
                    upload_session.storage_path,
                    tmp_path,
                    upload_session.maximum_size,
                )
            except StorageError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="Uploaded object could not be downloaded safely",
                ) from exc
            if downloaded_size != actual_size:
                raise HTTPException(
                    status_code=400,
                    detail="Uploaded object size changed during confirmation",
                )

            _validate_file_signature(tmp_path, extension)
            try:
                malware_scan_result = await scan_file(tmp_path)
            except MalwareScanError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            file_hash = await compute_file_hash(str(tmp_path))
            if body.checksum and body.checksum.lower() != file_hash:
                raise HTTPException(
                    status_code=400, detail="Uploaded object checksum mismatch"
                )

            if extension == ".pdf":
                extraction = await extract_pdf(str(tmp_path))
            elif extension == ".docx":
                extraction = await extract_docx(str(tmp_path))
            elif extension == ".txt":
                extracted_text = tmp_path.read_text(encoding="utf-8", errors="replace")
                extraction = {"text": extracted_text, "warnings": []}
            else:
                raise HTTPException(status_code=400, detail="Unsupported file type")

        extraction_error = extraction.get("error")
        extracted_text = extraction.get("text", "").strip()
        extraction_warnings = extraction.get("warnings", [])
        if extraction_error:
            extraction_warnings.append(extraction_error)
        if extraction_error in {
            "pdf_page_limit_exceeded",
            "pdf_text_limit_exceeded",
            "docx_size_limit_exceeded",
            "docx_text_limit_exceeded",
            "docx_uncompressed_size_limit_exceeded",
            "docx_suspicious_compression_ratio",
            "docx_invalid_package",
            "docx_unsafe_member_path",
        }:
            await create_audit_event(
                db,
                event_type="extraction.failed",
                user=current_user,
                resource_type="upload_session",
                resource_id=upload_session.id,
                details={
                    "proposal_id": upload_session.proposal_id,
                    "error": extraction_error,
                },
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
            failure_audited = True
            await db.commit()
            raise HTTPException(
                status_code=400,
                detail="Extraction failed because the document exceeded safe processing limits",
            )
        if not extracted_text:
            extraction_warnings.append(
                "No extractable text found; manual review required"
            )

        structured_fields = await extract_structured_fields(extracted_text)
        canonical_fields = canonicalize_extracted_fields(structured_fields)

        version_result = await db.execute(
            select(ProposalVersion)
            .where(ProposalVersion.id == upload_session.proposal_version_id)
            .with_for_update()
        )
        version = version_result.scalar_one_or_none()
        if not version:
            raise HTTPException(
                status_code=500, detail="Proposal version not found for upload session"
            )

        now = datetime.now(timezone.utc)
        is_main_proposal = upload_session.document_role == "main_proposal"
        # Serialised by the proposal-version row lock above. Replacing the main
        # document never supersedes supporting evidence, and replacing one
        # governed requirement never changes another requirement slot.
        if is_main_proposal:
            await db.execute(
                update(ProposalDocument)
                .where(
                    ProposalDocument.proposal_version_id == version.id,
                    ProposalDocument.is_primary.is_(True),
                    ProposalDocument.superseded_at.is_(None),
                )
                .values(is_primary=False, superseded_at=now)
            )
        elif upload_session.requirement_id is not None:
            await db.execute(
                update(ProposalDocument)
                .where(
                    ProposalDocument.proposal_version_id == version.id,
                    ProposalDocument.requirement_id == upload_session.requirement_id,
                    ProposalDocument.superseded_at.is_(None),
                )
                .values(is_primary=False, superseded_at=now)
            )

        doc = ProposalDocument(
            id=upload_session.document_id,
            proposal_version_id=upload_session.proposal_version_id,
            requirement_id=upload_session.requirement_id,
            file_name=upload_session.expected_file_name,
            file_type=extension.lstrip("."),
            file_size=actual_size,
            storage_path=upload_session.storage_path,
            sha256_hash=file_hash,
            malware_scan_result=malware_scan_result,
            document_role=upload_session.document_role,
            role_status="declared",
            extracted_text=extracted_text or None,
            extraction_version="2.0",
            ocr_used=bool(extraction.get("ocr_pages")),
            ocr_pages=extraction.get("ocr_pages", []),
            upload_completed_at=now,
            is_primary=is_main_proposal,
            superseded_at=None,
        )
        db.add(doc)

        for page in extraction.get("pages", []):
            db.add(
                DocumentPage(
                    document_id=doc.id,
                    page_number=int(page.get("page_number", 0)),
                    text=page.get("text") or None,
                    word_count=int(page.get("word_count", 0)),
                    ocr_used=bool(page.get("ocr_used", False)),
                    ocr_confidence=page.get("ocr_confidence"),
                    table_count=int(
                        page.get("table_count", len(page.get("tables", [])))
                    ),
                    image_count=int(page.get("image_count", 0)),
                )
            )
        upload_session.status = "consumed"
        upload_session.consumed_at = datetime.now(timezone.utc)
        upload_session.checksum = file_hash

        # Any package mutation invalidates an earlier applicant confirmation.
        version.package_status = "draft"
        version.package_manifest = {}
        version.package_hash = None
        version.package_policy_version = None
        version.package_confirmed_at = None
        version.package_confirmed_by = None
        if is_main_proposal:
            version.document_hash = file_hash
            version.content_hash = file_hash
            version.structured_data = canonical_fields

        await create_audit_event(
            db,
            event_type="document.confirmed",
            user=current_user,
            resource_type="proposal_document",
            resource_id=upload_session.document_id,
            details={
                "proposal_id": upload_session.proposal_id,
                "upload_session_id": upload_session.id,
                "file_name": upload_session.expected_file_name,
                "file_size": actual_size,
                "malware_scan_result": malware_scan_result,
                "document_role": upload_session.document_role,
                "requirement_id": upload_session.requirement_id,
                "is_primary": is_main_proposal,
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await create_audit_event(
            db,
            event_type="extraction.completed",
            user=current_user,
            resource_type="proposal_document",
            resource_id=upload_session.document_id,
            details={
                "proposal_id": upload_session.proposal_id,
                "schema_version": canonical_fields["schema_version"],
                "field_count": len(canonical_fields["fields"]),
                "word_count": len(extracted_text.split()) if extracted_text else 0,
                "page_count": len(extraction.get("pages", [])),
                "ocr_pages": extraction.get("ocr_pages", []),
                "warnings": extraction_warnings,
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await db.commit()

        if extracted_text:
            try:
                pool = await arq.create_pool(settings.arq_redis_settings)
                try:
                    await pool.enqueue_job("extract_document", doc.id)
                finally:
                    close_pool = getattr(pool, "aclose", None)
                    if close_pool is None:
                        close_pool = pool.close
                    await close_pool()
            except Exception:
                extraction_warnings.append("Background extraction could not be queued")

        return {
            "document_id": upload_session.document_id,
            "status": "confirmed",
            "extraction_status": "complete"
            if extracted_text
            else "manual_review_required",
            "word_count": len(extracted_text.split()) if extracted_text else 0,
            "page_count": len(extraction.get("pages", [])),
            "ocr_pages": extraction.get("ocr_pages", []),
            "warnings": extraction_warnings,
        }
    except HTTPException as exc:
        failed_session = upload_session if session_owned_by_current_user and "upload_session" in locals() else None
        failure_identity = (
            (failed_session.id, failed_session.proposal_id, failed_session.document_id)
            if failed_session is not None
            else None
        )
        if failed_session is not None and failed_session.status == "pending":
            failed_session.status = "failed"
        # Never commit partially-applied extraction, version, or primary-document
        # mutations merely to record a failure. Roll back first, then update only
        # the upload-session lifecycle in a clean transaction.
        rollback = getattr(db, "rollback", None)
        if rollback is not None:
            await rollback()
        if failure_identity is not None:
            await db.execute(
                update(UploadSession)
                .where(
                    UploadSession.id == failure_identity[0],
                    UploadSession.status == "pending",
                )
                .values(status="failed")
            )
            await db.commit()
        if failure_identity is not None and not failure_audited:
            await _record_extraction_failure(
                failure_identity[0],
                failure_identity[1],
                failure_identity[2],
                current_user,
                request,
                reason=str(exc.detail),
                status_code=exc.status_code,
            )
        raise
    except Exception as exc:
        failed_session = upload_session if session_owned_by_current_user and "upload_session" in locals() else None
        failure_identity = (
            (failed_session.id, failed_session.proposal_id, failed_session.document_id)
            if failed_session is not None
            else None
        )
        if failed_session is not None and failed_session.status == "pending":
            failed_session.status = "failed"
        rollback = getattr(db, "rollback", None)
        if rollback is not None:
            await rollback()
        if failure_identity is not None:
            await db.execute(
                update(UploadSession)
                .where(
                    UploadSession.id == failure_identity[0],
                    UploadSession.status == "pending",
                )
                .values(status="failed")
            )
            await db.commit()
        if failure_identity is not None and not failure_audited:
            await _record_extraction_failure(
                failure_identity[0],
                failure_identity[1],
                failure_identity[2],
                current_user,
                request,
                reason=type(exc).__name__,
            )
        raise HTTPException(status_code=500, detail="Failed to confirm upload") from exc
