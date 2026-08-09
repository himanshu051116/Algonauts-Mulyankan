import pytest

from app.models.proposal import AuditEvent
from app.models.user import User, UserRole
from backend.scripts.bootstrap_admin import bootstrap_admin, validate_bootstrap_identity


class Result:
    def __init__(self, user):
        self.user = user

    def scalar_one_or_none(self):
        return self.user


class FakeBootstrapDb:
    def __init__(self):
        self.user = None
        self.audit_events = []
        self.commits = 0

    async def execute(self, _statement):
        return Result(self.user)

    def add(self, item):
        if isinstance(item, User):
            self.user = item
        elif isinstance(item, AuditEvent):
            self.audit_events.append(item)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1


def test_bootstrap_refuses_unsafe_default_email():
    with pytest.raises(ValueError):
        validate_bootstrap_identity("", "admin@example.com")


@pytest.mark.asyncio
async def test_bootstrap_admin_is_idempotent():
    db = FakeBootstrapDb()

    first = await bootstrap_admin(db, "supabase-admin-id", "admin@coal.gov.in")
    second = await bootstrap_admin(db, "supabase-admin-id", "admin@coal.gov.in")

    assert first.created is True
    assert first.changed is True
    assert second.created is False
    assert second.changed is False
    assert db.user.role == UserRole.ADMINISTRATOR
    assert db.user.is_active is True
    assert db.user.is_verified is True
    assert len(db.audit_events) == 1
