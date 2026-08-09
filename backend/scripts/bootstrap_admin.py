"""One-time administrator bootstrap.

Run with explicit environment configuration, for example:

    BOOTSTRAP_ADMIN_UID=<supabase-user-id> BOOTSTRAP_ADMIN_EMAIL=admin@example.gov.in \
    python -m backend.scripts.bootstrap_admin
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_factory, init_db
from app.models.proposal import AuditEvent
from app.models.user import User, UserRole

UNSAFE_ADMIN_EMAILS = {
    "admin@example.com",
    "admin@example.gov.in",
    "administrator@example.com",
    "test@example.com",
}
UNSAFE_ADMIN_UIDS = {"", "admin", "administrator", "test", "changeme", "change-me"}


@dataclass(frozen=True)
class BootstrapResult:
    user_id: str
    email: str
    created: bool
    changed: bool


def _clean(value: str | None) -> str:
    return (value or "").strip()


def validate_bootstrap_identity(admin_uid: str | None, admin_email: str | None) -> tuple[str, str]:
    uid = _clean(admin_uid)
    email = _clean(admin_email).lower()

    if not uid and not email:
        raise ValueError("Set BOOTSTRAP_ADMIN_UID or BOOTSTRAP_ADMIN_EMAIL explicitly.")
    if uid.lower() in UNSAFE_ADMIN_UIDS:
        raise ValueError("Refusing unsafe bootstrap administrator UID.")
    if email in UNSAFE_ADMIN_EMAILS or (email and "@" not in email):
        raise ValueError("Refusing unsafe bootstrap administrator email.")
    if not uid:
        uid = f"bootstrap-admin-{uuid4()}"
    if not email:
        email = f"{uid}@bootstrap.local"
    return uid, email


async def bootstrap_admin(
    db: AsyncSession,
    admin_uid: str | None,
    admin_email: str | None,
) -> BootstrapResult:
    uid, email = validate_bootstrap_identity(admin_uid, admin_email)

    result = await db.execute(
        select(User).where(or_(User.id == uid, User.email == email)).limit(1)
    )
    user = result.scalar_one_or_none()
    created = user is None
    before = None

    if user is None:
        user = User(
            id=uid,
            email=email,
            role=UserRole.ADMINISTRATOR,
            is_active=True,
            is_verified=True,
            approval_status="approved",
            approved_by="bootstrap",
            approved_at=datetime.now(timezone.utc),
        )
        db.add(user)
        changed = True
    else:
        before = {
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "is_active": user.is_active,
            "is_verified": user.is_verified,
            "approval_status": user.approval_status,
        }
        changed = (
            user.role != UserRole.ADMINISTRATOR
            or not user.is_active
            or not user.is_verified
            or user.approval_status != "approved"
        )
        user.role = UserRole.ADMINISTRATOR
        user.is_active = True
        user.is_verified = True
        user.approval_status = "approved"
        user.approved_by = "bootstrap"
        user.approved_at = user.approved_at or datetime.now(timezone.utc)

    await db.flush()

    if created or changed:
        db.add(
            AuditEvent(
                user_id=user.id,
                event_type="administrator.bootstrap",
                resource_type="user",
                resource_id=user.id,
                details={
                    "email": user.email,
                    "created": created,
                    "before": before,
                    "after": {
                        "role": UserRole.ADMINISTRATOR.value,
                        "is_active": True,
                        "is_verified": True,
                        "approval_status": "approved",
                    },
                },
            )
        )

    await db.commit()
    return BootstrapResult(
        user_id=user.id,
        email=user.email,
        created=created,
        changed=created or changed,
    )


async def main() -> None:
    admin_uid = settings.bootstrap_admin_uid
    admin_email = settings.bootstrap_admin_email
    validate_bootstrap_identity(admin_uid, admin_email)

    await init_db()
    async with async_session_factory() as db:
        result = await bootstrap_admin(db, admin_uid, admin_email)
    action = "created or updated" if result.changed else "already configured"
    print(f"Administrator {action}: {result.email} ({result.user_id})")


if __name__ == "__main__":
    asyncio.run(main())
