"""Shared SQLAlchemy declarative base.

Keeping the metadata definition independent from engine construction allows Alembic
offline migrations and schema-inspection tools to run without importing a database
driver or opening a connection.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
