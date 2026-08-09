import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import arq
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.domain import ProposalStatus, proposal_transition_allowed
from app.models.proposal import (
    ModelRun,
    Proposal,
    ProposalDocument,
    ProposalVersion,
    ReviewerAssignment,
    UploadSession,
)
from app.models.user import User, UserRole
from app.schemas.proposal import (
    ProposalCreate,
    ProposalListResponse,
    ProposalResponse,
    ProposalUpdate,
    ProposalVersionCreate,
    ProposalVersionListResponse,
    ProposalVersionResponse,
    SubmissionPackageConfirmRequest,
    SubmissionPackageResponse,
    UploadUrlRequest,
    UploadUrlResponse,
)
from app.services.access import get_proposal_for_user, reviewer_model_output_is_blinded
from app.services.audit import create_audit_event
from app.services.schemes import ensure_proposal_active_scheme, get_active_scheme_or_422
from app.services.storage import get_signed_upload_url
from app.services.submission_packages import (
    SubmissionPackagePolicyError,
    build_submission_package_summary,
    requirement_for,
)

router = APIRouter()

UPLOAD_CONTENT_TYPES = {
    ".pdf": ["application/pdf"],
    ".docx": [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ],
    ".txt": ["text/plain"],
}


def _safe_upload_name(file_name: str) -> str:
    return Path(file_name).name.replace("\\", "_").replace("/", "_")


def _proposal_response(
    proposal: Proposal,
    *,
    executive_summary: str | None = None,
    document_id: str | None = None,
    document_file_name: str | None = None,
    status_override: str | None = None,
) -> ProposalResponse:
    return ProposalResponse(
        id=proposal.id,
        title=proposal.title,
        scheme_id=proposal.scheme_id,
        status=status_override or proposal.status,
        current_version=proposal.current_version,
        owner_id=proposal.owner_id,
        executive_summary=executive_summary,
        document_id=document_id,
        document_file_name=document_file_name,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
    )


async def _latest_version(
    db: AsyncSession,
    proposal_id: str,
    *,
    for_update: bool = False,
) -> ProposalVersion | None:
    statement = (
        select(ProposalVersion)
        .where(ProposalVersion.proposal_id == proposal_id)
        .order_by(ProposalVersion.version_number.desc())
        .limit(1)
    )
    if for_update:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    return result.scalar_one_or_none()


async def _latest_document(
    db: AsyncSession, proposal_version_id: str
) -> ProposalDocument | None:
    result = await db.execute(
        select(ProposalDocument)
        .where(
            ProposalDocument.proposal_version_id == proposal_version_id,
            ProposalDocument.is_primary.is_(True),
            ProposalDocument.document_role == "main_proposal",
            ProposalDocument.superseded_at.is_(None),
        )
        .order_by(ProposalDocument.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _editable_current_version(
    db: AsyncSession, proposal: Proposal, *, for_update: bool = False
) -> ProposalVersion:
    """Return an editable version without mutating an evaluated snapshot.

    A requested revision must branch to a new proposal version before the
    applicant changes its title or document. This preserves the exact content
    that was previously scored and reviewed.
    """

    version = await _latest_version(db, proposal.id, for_update=for_update)
    if version is None or version.version_number != proposal.current_version:
        raise HTTPException(
            status_code=409, detail="Current proposal version is missing or inconsistent"
        )
    if proposal.status == ProposalStatus.REVISION_REQUIRED.value:
        run_result = await db.execute(
            select(ModelRun.id)
            .where(ModelRun.proposal_version_id == version.id)
            .limit(1)
        )
        if run_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Create a new proposal version before editing or resubmitting "
                    "a requested revision"
                ),
            )
    return version


def _version_response(version: ProposalVersion) -> ProposalVersionResponse:
    return ProposalVersionResponse.model_validate(version)


@router.get("/", response_model=ProposalListResponse)
async def list_proposals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    query = select(Proposal)
    if current_user.role == UserRole.APPLICANT:
        query = query.where(Proposal.owner_id == current_user.id)
    elif current_user.role in (
        UserRole.TECHNICAL_REVIEWER,
        UserRole.FINANCIAL_REVIEWER,
        UserRole.SCRUTINY_OFFICER,
    ):
        assigned_ids = select(ReviewerAssignment.proposal_id).where(
            ReviewerAssignment.reviewer_id == current_user.id
        )
        query = query.where(
            (Proposal.owner_id == current_user.id) | (Proposal.id.in_(assigned_ids))
        )

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    result = await db.execute(
        query.offset(skip).limit(limit).order_by(Proposal.updated_at.desc())
    )
    proposals = result.scalars().all()

    summary_by_proposal: dict[str, str | None] = {}
    if proposals:
        summary_result = await db.execute(
            select(ProposalVersion.proposal_id, ProposalVersion.executive_summary)
            .join(Proposal, Proposal.id == ProposalVersion.proposal_id)
            .where(
                Proposal.id.in_([proposal.id for proposal in proposals]),
                ProposalVersion.version_number == Proposal.current_version,
            )
        )
        summary_by_proposal = {
            proposal_id: summary for proposal_id, summary in summary_result.all()
        }

    document_by_proposal: dict[str, tuple[str, str]] = {}
    if proposals:
        document_result = await db.execute(
            select(
                ProposalVersion.proposal_id,
                ProposalDocument.id,
                ProposalDocument.file_name,
            )
            .join(
                ProposalDocument,
                ProposalDocument.proposal_version_id == ProposalVersion.id,
            )
            .join(Proposal, Proposal.id == ProposalVersion.proposal_id)
            .where(
                Proposal.id.in_([proposal.id for proposal in proposals]),
                ProposalVersion.version_number == Proposal.current_version,
                ProposalDocument.is_primary.is_(True),
                ProposalDocument.superseded_at.is_(None),
            )
            .order_by(ProposalDocument.created_at.desc())
        )
        for proposal_id, document_id, file_name in document_result.all():
            document_by_proposal.setdefault(proposal_id, (document_id, file_name))

    return ProposalListResponse(
        proposals=[
            _proposal_response(
                proposal,
                executive_summary=summary_by_proposal.get(proposal.id),
                document_id=(document_by_proposal.get(proposal.id) or (None, None))[0],
                document_file_name=(
                    document_by_proposal.get(proposal.id) or (None, None)
                )[1],
                status_override=(
                    "shadow_review"
                    if await reviewer_model_output_is_blinded(
                        db, current_user, proposal.id
                    )
                    else None
                ),
            )
            for proposal in proposals
        ],
        total=total or 0,
        skip=skip,
        limit=limit,
    )


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=ProposalResponse)
async def create_proposal(
    body: ProposalCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scheme = await get_active_scheme_or_422(db, body.scheme_code)

    proposal = Proposal(
        owner_id=current_user.id,
        scheme_id=scheme.id,
        title=body.title,
        status=ProposalStatus.DRAFT.value,
    )
    db.add(proposal)
    await db.flush()

    version = ProposalVersion(
        proposal_id=proposal.id,
        version_number=1,
        title=body.title,
        executive_summary=body.executive_summary,
    )
    db.add(version)
    await db.flush()

    await create_audit_event(
        db,
        event_type="proposal.created",
        user=current_user,
        resource_type="proposal",
        resource_id=proposal.id,
        details={
            "title": body.title,
            "scheme_code": body.scheme_code,
            "has_executive_summary": bool(body.executive_summary),
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    await db.refresh(proposal)

    return _proposal_response(proposal, executive_summary=version.executive_summary)


@router.get("/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    proposal = await get_proposal_for_user(
        db,
        current_user,
        proposal_id,
        conceal_existence=True,
    )

    version = await _latest_version(db, proposal.id)
    document = await _latest_document(db, version.id) if version else None
    return _proposal_response(
        proposal,
        executive_summary=version.executive_summary if version else None,
        document_id=document.id if document else None,
        document_file_name=document.file_name if document else None,
        status_override=(
            "shadow_review"
            if await reviewer_model_output_is_blinded(db, current_user, proposal.id)
            else None
        ),
    )


@router.patch("/{proposal_id}", response_model=ProposalResponse)
async def update_proposal(
    proposal_id: str,
    body: ProposalUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Proposal).where(
            Proposal.id == proposal_id, Proposal.owner_id == current_user.id
        )
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status not in ("draft", "revision_required"):
        raise HTTPException(
            status_code=400, detail="Only draft proposals can be updated"
        )
    await ensure_proposal_active_scheme(db, proposal)

    current_version = await _editable_current_version(
        db, proposal, for_update=True
    )
    changed: dict[str, str] = {}
    if (
        body.title is not None
        and body.title.strip()
        and body.title.strip() != proposal.title
    ):
        changed["title"] = proposal.title
        proposal.title = body.title.strip()
        current_version.title = proposal.title
    if not changed:
        raise HTTPException(
            status_code=400, detail="No supported proposal changes supplied"
        )

    await create_audit_event(
        db,
        event_type="proposal.updated",
        user=current_user,
        resource_type="proposal",
        resource_id=proposal_id,
        details={"changed_fields": list(changed.keys())},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    await db.refresh(proposal)
    version = await _latest_version(db, proposal.id)
    return _proposal_response(
        proposal,
        executive_summary=version.executive_summary if version else None,
    )


@router.get(
    "/{proposal_id}/versions",
    response_model=ProposalVersionListResponse,
)
async def list_proposal_versions(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_proposal_for_user(db, current_user, proposal_id, conceal_existence=True)
    result = await db.execute(
        select(ProposalVersion)
        .where(ProposalVersion.proposal_id == proposal_id)
        .order_by(ProposalVersion.version_number.desc())
    )
    return ProposalVersionListResponse(
        versions=[_version_response(version) for version in result.scalars().all()]
    )


@router.post(
    "/{proposal_id}/versions",
    status_code=status.HTTP_201_CREATED,
    response_model=ProposalVersionResponse,
)
async def create_proposal_version(
    proposal_id: str,
    body: ProposalVersionCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    proposal_result = await db.execute(
        select(Proposal)
        .where(Proposal.id == proposal_id, Proposal.owner_id == current_user.id)
        .with_for_update()
    )
    proposal = proposal_result.scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status not in (
        ProposalStatus.DRAFT.value,
        ProposalStatus.REVISION_REQUIRED.value,
    ):
        raise HTTPException(
            status_code=409,
            detail="A new version can only be created for a draft or requested revision",
        )
    await ensure_proposal_active_scheme(db, proposal)

    previous = await _latest_version(db, proposal_id, for_update=True)
    if previous is None:
        raise HTTPException(
            status_code=409, detail="Previous proposal version is missing"
        )
    if previous.version_number != proposal.current_version:
        raise HTTPException(
            status_code=409, detail="Proposal version state is inconsistent"
        )

    new_version = ProposalVersion(
        proposal_id=proposal.id,
        version_number=previous.version_number + 1,
        previous_version_id=previous.id,
        rubric_version_id=previous.rubric_version_id,
        guideline_version_id=previous.guideline_version_id,
        title=previous.title or proposal.title,
        executive_summary=(
            body.executive_summary
            if body.executive_summary is not None
            else previous.executive_summary
        ),
        structured_data={},
    )
    db.add(new_version)
    await db.flush()
    proposal.current_version = new_version.version_number

    await create_audit_event(
        db,
        event_type="proposal.version_created",
        user=current_user,
        resource_type="proposal_version",
        resource_id=new_version.id,
        details={
            "proposal_id": proposal.id,
            "version_number": new_version.version_number,
            "previous_version_id": previous.id,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    await db.refresh(new_version)
    return _version_response(new_version)


@router.post("/{proposal_id}/upload-url", response_model=UploadUrlResponse)
async def get_upload_url(
    proposal_id: str,
    body: UploadUrlRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Proposal).where(
            Proposal.id == proposal_id, Proposal.owner_id == current_user.id
        )
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status not in ("draft", "revision_required"):
        raise HTTPException(
            status_code=400, detail="Cannot upload to a non-draft proposal"
        )
    scheme = await ensure_proposal_active_scheme(db, proposal)

    version = await _editable_current_version(db, proposal)

    safe_name = _safe_upload_name(body.file_name)
    extension = Path(safe_name).suffix.lower()
    allowed_content_types = UPLOAD_CONTENT_TYPES.get(extension)
    if not allowed_content_types:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    requirement_id = body.requirement_id
    if requirement_id is None and body.document_role == "main_proposal":
        requirement_id = "proposal_body"

    max_bytes = settings.max_file_size_mb * 1024 * 1024
    if requirement_id is not None:
        try:
            _policy, requirement = requirement_for(scheme.code, requirement_id)
        except SubmissionPackagePolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if body.document_role != requirement["document_role"]:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Requirement '{requirement_id}' must use document role "
                    f"'{requirement['document_role']}'"
                ),
            )
        if extension.lstrip(".") not in requirement["allowed_types"]:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"File type '{extension.lstrip('.')}' is not permitted for "
                    f"requirement '{requirement_id}'"
                ),
            )
        max_bytes = min(max_bytes, int(requirement["max_size_mb"]) * 1024 * 1024)

    if body.file_size <= 0 or body.file_size > max_bytes:
        raise HTTPException(
            status_code=400, detail="File size is outside the permitted limit"
        )

    doc_id = str(uuid.uuid4())
    storage_path = (
        f"proposals/{proposal_id}/v{version.version_number}/{doc_id}_{safe_name}"
    )
    upload_session = UploadSession(
        id=str(uuid.uuid4()),
        owner_id=current_user.id,
        proposal_id=proposal_id,
        proposal_version_id=version.id,
        document_id=doc_id,
        storage_path=storage_path,
        expected_file_name=safe_name,
        requirement_id=requirement_id,
        document_role=body.document_role,
        allowed_content_types=allowed_content_types,
        maximum_size=max_bytes,
        expected_size=body.file_size,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(upload_session)
    await create_audit_event(
        db,
        event_type="upload_session.created",
        user=current_user,
        resource_type="upload_session",
        resource_id=upload_session.id,
        details={
            "proposal_id": proposal_id,
            "file_name": safe_name,
            "file_size": body.file_size,
            "document_role": body.document_role,
            "requirement_id": requirement_id,
        },
    )
    await db.commit()

    upload_url = await get_signed_upload_url(
        storage_path, body.file_size, allowed_content_types[0]
    )

    return UploadUrlResponse(
        upload_url=upload_url,
        upload_session_id=upload_session.id,
        document_id=doc_id,
        storage_path=storage_path,
        requirement_id=requirement_id,
        expires_in=3600,
    )


async def _submission_package_summary(
    db: AsyncSession, proposal: Proposal, version: ProposalVersion, scheme_code: str
) -> dict:
    result = await db.execute(
        select(ProposalDocument)
        .where(ProposalDocument.proposal_version_id == version.id)
        .order_by(ProposalDocument.created_at.asc())
    )
    return build_submission_package_summary(
        scheme_code=scheme_code,
        proposal_id=proposal.id,
        version=version,
        documents=result.scalars().all(),
    )


@router.get(
    "/{proposal_id}/submission-package",
    response_model=SubmissionPackageResponse,
)
async def get_submission_package(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    proposal = await get_proposal_for_user(
        db, current_user, proposal_id, conceal_existence=True
    )
    scheme = await ensure_proposal_active_scheme(db, proposal)
    version = await _latest_version(db, proposal.id)
    if version is None:
        raise HTTPException(status_code=409, detail="Current proposal version is missing")
    try:
        summary = await _submission_package_summary(db, proposal, version, scheme.code)
    except SubmissionPackagePolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SubmissionPackageResponse.model_validate(summary)


@router.post(
    "/{proposal_id}/submission-package/confirm",
    response_model=SubmissionPackageResponse,
)
async def confirm_submission_package(
    proposal_id: str,
    body: SubmissionPackageConfirmRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Proposal).where(
            Proposal.id == proposal_id, Proposal.owner_id == current_user.id
        )
    )
    proposal = result.scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status not in (
        ProposalStatus.DRAFT.value,
        ProposalStatus.REVISION_REQUIRED.value,
    ):
        raise HTTPException(
            status_code=400, detail="Only a draft proposal package can be confirmed"
        )
    if not body.confirm_declared_roles:
        raise HTTPException(
            status_code=422,
            detail="Applicant confirmation of declared document roles is required",
        )
    scheme = await ensure_proposal_active_scheme(db, proposal)
    version = await _editable_current_version(db, proposal, for_update=True)
    try:
        summary = await _submission_package_summary(db, proposal, version, scheme.code)
    except SubmissionPackagePolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not summary["ready_to_confirm"]:
        version.package_status = "incomplete"
        await db.commit()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "submission_package_incomplete",
                "missing_mandatory_requirements": summary[
                    "missing_mandatory_requirements"
                ],
                "invalid_requirements": summary["invalid_requirements"],
                "unassigned_document_ids": summary["unassigned_document_ids"],
            },
        )

    confirmed_document_ids = [
        document["id"] for document in summary["documents"]
    ]
    if confirmed_document_ids:
        await db.execute(
            update(ProposalDocument)
            .where(ProposalDocument.id.in_(confirmed_document_ids))
            .values(
                role_status="confirmed",
                role_confidence=1.0,
                role_reason=(
                    "Applicant confirmed this document role when sealing the "
                    "governed submission package."
                ),
            )
        )

    version.package_status = "confirmed"
    version.package_manifest = summary["canonical_manifest"]
    version.package_hash = summary["computed_package_hash"]
    version.package_policy_version = summary["policy_version"]
    version.package_confirmed_at = datetime.now(timezone.utc)
    version.package_confirmed_by = current_user.id
    await create_audit_event(
        db,
        event_type="submission_package.confirmed",
        user=current_user,
        resource_type="proposal_version",
        resource_id=version.id,
        details={
            "proposal_id": proposal.id,
            "version_number": version.version_number,
            "policy_version": version.package_policy_version,
            "package_hash": version.package_hash,
            "document_count": len(summary["documents"]),
            "declared_roles_confirmed": True,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    await db.refresh(version)
    confirmed = await _submission_package_summary(db, proposal, version, scheme.code)
    return SubmissionPackageResponse.model_validate(confirmed)


@router.post("/{proposal_id}/submit")
async def submit_proposal(
    proposal_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Proposal).where(
            Proposal.id == proposal_id, Proposal.owner_id == current_user.id
        ).with_for_update()
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status in {
        ProposalStatus.EVALUATING.value,
        ProposalStatus.HUMAN_REVIEW.value,
        ProposalStatus.ADJUDICATION.value,
        ProposalStatus.COMMITTEE_REVIEW.value,
        ProposalStatus.APPROVED.value,
        ProposalStatus.REJECTED.value,
    }:
        return {"id": proposal_id, "status": proposal.status}
    if proposal.status not in (
        ProposalStatus.DRAFT.value,
        ProposalStatus.REVISION_REQUIRED.value,
        ProposalStatus.SUBMITTED.value,
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot submit proposal in '{proposal.status}' status",
        )
    scheme = await ensure_proposal_active_scheme(db, proposal)

    version = await _editable_current_version(db, proposal)
    try:
        package_summary = await _submission_package_summary(
            db, proposal, version, scheme.code
        )
    except SubmissionPackagePolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if (
        version.package_status != "confirmed"
        or not package_summary["ready_to_confirm"]
        or not version.package_hash
        or version.package_hash != package_summary["computed_package_hash"]
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "submission_package_not_confirmed",
                "message": (
                    "Confirm the complete governed submission package before "
                    "submitting for evaluation."
                ),
                "missing_mandatory_requirements": package_summary[
                    "missing_mandatory_requirements"
                ],
                "invalid_requirements": package_summary["invalid_requirements"],
            },
        )

    document_result = await db.execute(
        select(ProposalDocument.id)
        .where(
            ProposalDocument.proposal_version_id == version.id,
            ProposalDocument.is_primary.is_(True),
            ProposalDocument.document_role == "main_proposal",
            ProposalDocument.superseded_at.is_(None),
            ProposalDocument.upload_completed_at.isnot(None),
            ProposalDocument.extracted_text.isnot(None),
            func.length(func.trim(ProposalDocument.extracted_text)) > 0,
        )
        .limit(1)
    )
    if document_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "A confirmed document with extractable text is required before "
                "submission. Re-upload the file or request OCR/manual processing."
            ),
        )

    old_status = proposal.status
    is_queue_retry = old_status == ProposalStatus.SUBMITTED.value
    if not proposal_transition_allowed(old_status, ProposalStatus.SUBMITTED):
        raise HTTPException(
            status_code=409, detail="Invalid proposal status transition"
        )
    proposal.status = ProposalStatus.SUBMITTED.value
    if is_queue_retry:
        await create_audit_event(
            db,
            event_type="evaluation.initial_queue_retry_requested",
            user=current_user,
            resource_type="proposal",
            resource_id=proposal_id,
            details={"proposal_version_id": version.id},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    else:
        await create_audit_event(
            db,
            event_type="proposal.submitted",
            user=current_user,
            resource_type="proposal",
            resource_id=proposal_id,
            details={
                "proposal_version_id": version.id,
                "package_hash": version.package_hash,
                "package_policy_version": version.package_policy_version,
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await create_audit_event(
            db,
            event_type="proposal.status_transition",
            user=current_user,
            resource_type="proposal",
            resource_id=proposal_id,
            details={
                "from": old_status,
                "to": proposal.status,
                "reason": "submitted_for_evaluation",
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

    try:
        pool = await arq.create_pool(settings.arq_redis_settings)
        try:
            await pool.enqueue_job(
                "evaluate_proposal",
                proposal_id,
                scheme_code=scheme.code,
                trigger_user_id=current_user.id,
            )
            proposal.status = ProposalStatus.EVALUATING.value
        finally:
            close_pool = getattr(pool, "aclose", None)
            if close_pool is None:
                close_pool = pool.close
            await close_pool()
    except Exception as exc:
        proposal.status = ProposalStatus.SUBMITTED.value
        await create_audit_event(
            db,
            event_type="evaluation.initial_queue_failed",
            user=current_user,
            resource_type="proposal",
            resource_id=proposal_id,
            details={
                "proposal_version_id": version.id,
                "retry": is_queue_retry,
                "exception_type": type(exc).__name__,
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await db.commit()
        raise HTTPException(
            status_code=503,
            detail=(
                "Evaluation queue is temporarily unavailable. Retry this "
                "submitted proposal; its sealed package was preserved."
            ),
        ) from exc

    await db.commit()
    return {"id": proposal_id, "status": ProposalStatus.EVALUATING.value}
