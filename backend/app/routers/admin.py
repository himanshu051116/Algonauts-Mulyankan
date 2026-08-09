import inspect
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_authenticated_user, require_role
from app.database import get_db
from app.domain import ApprovalStatus
from app.models.proposal import Proposal
from app.models.user import User, UserRole
from app.schemas.admin import (
    AdministrativeOverrideRequest,
    RoleAssignRequest,
    RoleAssignResponse,
    UserApproveResponse,
    UserListResponse,
    UserMeResponse,
    UserResponse,
)
from app.services.audit import create_audit_event

logger = logging.getLogger("mulyankan.admin")

router = APIRouter()


async def _lock_admin_governance(db: AsyncSession) -> None:
    """Serialise administrator demotion/suspension decisions on PostgreSQL.

    Lightweight test doubles and non-PostgreSQL development databases do not
    expose a synchronous ``get_bind`` implementation, so locking is skipped
    there while the count check still applies.
    """

    get_bind = getattr(db, "get_bind", None)
    if get_bind is None:
        return
    bind = get_bind()
    if inspect.isawaitable(bind):
        close = getattr(bind, "close", None)
        if callable(close):
            close()
        return
    dialect_name = getattr(getattr(bind, "dialect", None), "name", None)
    if dialect_name == "postgresql":
        # Stable application-specific advisory lock id. Released at transaction end.
        await db.execute(text("SELECT pg_advisory_xact_lock(7120260705)"))


@router.get("/users", response_model=UserListResponse)
async def list_users(
    current_user: User = Depends(require_role(UserRole.ADMINISTRATOR, UserRole.AUDITOR)),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    total_result = await db.execute(
        select(func.count()).select_from(select(User).subquery())
    )
    total = total_result.scalar() or 0

    result = await db.execute(
        select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)
    )
    users = result.scalars().all()

    return UserListResponse(
        total=total,
        skip=skip,
        limit=limit,
        users=[
            UserResponse(
                id=u.id,
                email=u.email,
                role=u.role.value if hasattr(u.role, "value") else str(u.role),
                full_name=u.full_name,
                organisation=u.organisation,
                is_active=u.is_active,
                is_verified=u.is_verified,
                approval_status=u.approval_status,
                created_at=u.created_at,
            )
            for u in users
        ],
    )


@router.get("/users/me", response_model=UserMeResponse)
async def get_current_user_info(
    current_user: User = Depends(get_authenticated_user),
):
    return UserMeResponse(
        id=current_user.id,
        email=current_user.email,
        role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        is_active=current_user.is_active,
        is_verified=current_user.is_verified,
        approval_status=current_user.approval_status,
        full_name=current_user.full_name,
        organisation=current_user.organisation,
    )


@router.post("/users/{user_id}/approve", response_model=UserApproveResponse)
async def approve_user(
    user_id: str,
    request: Request,
    current_user: User = Depends(require_role(UserRole.ADMINISTRATOR)),
    db: AsyncSession = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Administrators cannot approve themselves")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = True
    user.approval_status = ApprovalStatus.APPROVED.value
    user.approved_by = current_user.id
    user.approved_at = datetime.now(timezone.utc)

    await create_audit_event(
        db,
        event_type="user.approved",
        user=current_user,
        resource_type="user",
        resource_id=user_id,
        details={"target_email": user.email},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()

    return UserApproveResponse(user_id=user_id, status="approved")


@router.post("/users/{user_id}/roles", response_model=RoleAssignResponse)
async def assign_role(
    user_id: str,
    body: RoleAssignRequest,
    request: Request,
    current_user: User = Depends(require_role(UserRole.ADMINISTRATOR)),
    db: AsyncSession = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Administrators cannot change their own role")

    if not body.reason.strip():
        raise HTTPException(status_code=400, detail="A reason is required for role changes")

    try:
        new_role = UserRole(body.role)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{body.role}'. Valid roles: {[r.value for r in UserRole]}",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Preserve at least one administrator
    if user.role == UserRole.ADMINISTRATOR and new_role != UserRole.ADMINISTRATOR:
        await _lock_admin_governance(db)
        admin_count = await db.execute(
            select(func.count()).where(User.role == UserRole.ADMINISTRATOR)
        )
        if (admin_count.scalar() or 0) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the last administrator. Promote another user to administrator first.",
            )

    old_role = user.role.value if hasattr(user.role, "value") else str(user.role)
    user.role = new_role
    user.updated_at = func.now()

    await create_audit_event(
        db,
        event_type="user.role_changed",
        user=current_user,
        resource_type="user",
        resource_id=user_id,
        details={
            "target_email": user.email,
            "old_role": old_role,
            "new_role": body.role,
            "reason": body.reason,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()

    return RoleAssignResponse(user_id=user_id, role=body.role, status="updated")


@router.post("/users/{user_id}/suspend", response_model=UserApproveResponse)
async def suspend_user(
    user_id: str,
    request: Request,
    current_user: User = Depends(require_role(UserRole.ADMINISTRATOR)),
    db: AsyncSession = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Administrators cannot suspend themselves")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == UserRole.ADMINISTRATOR:
        await _lock_admin_governance(db)
        admin_count = await db.execute(
            select(func.count()).where(
                User.role == UserRole.ADMINISTRATOR,
                User.is_active.is_(True),
            )
        )
        if (admin_count.scalar() or 0) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot suspend the last active administrator.",
            )
    user.is_active = False
    user.approval_status = ApprovalStatus.SUSPENDED.value
    user.updated_at = func.now()
    await create_audit_event(
        db,
        event_type="user.suspended",
        user=current_user,
        resource_type="user",
        resource_id=user_id,
        details={"target_email": user.email},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return UserApproveResponse(user_id=user_id, status="suspended")


@router.post("/users/{user_id}/reactivate", response_model=UserApproveResponse)
async def reactivate_user(
    user_id: str,
    request: Request,
    current_user: User = Depends(require_role(UserRole.ADMINISTRATOR)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = True
    user.approval_status = ApprovalStatus.APPROVED.value
    user.updated_at = func.now()
    await create_audit_event(
        db,
        event_type="user.reactivated",
        user=current_user,
        resource_type="user",
        resource_id=user_id,
        details={"target_email": user.email},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return UserApproveResponse(user_id=user_id, status="reactivated")


@router.post("/proposals/{proposal_id}/override-status")
async def override_proposal_status(
    proposal_id: str,
    body: AdministrativeOverrideRequest,
    request: Request,
    current_user: User = Depends(require_role(UserRole.ADMINISTRATOR)),
    db: AsyncSession = Depends(get_db),
):
    if not body.reason.strip():
        raise HTTPException(status_code=400, detail="A reason is required for administrative overrides")
    result = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    old_status = proposal.status
    proposal.status = body.status.value
    await create_audit_event(
        db,
        event_type="administrative.override",
        user=current_user,
        resource_type="proposal",
        resource_id=proposal_id,
        details={"from": old_status, "to": body.status.value, "reason": body.reason},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await create_audit_event(
        db,
        event_type="proposal.status_transition",
        user=current_user,
        resource_type="proposal",
        resource_id=proposal_id,
        details={"from": old_status, "to": body.status.value, "reason": "administrative_override"},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return {"proposal_id": proposal_id, "status": body.status.value}
