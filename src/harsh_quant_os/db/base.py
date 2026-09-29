"""Declarative base for every persisted model.

The naming convention is not cosmetic: Alembic reverses migrations by dropping
constraints by name, so an unnamed or auto-named constraint cannot be
reliably dropped on downgrade. Fixing the convention here is what makes
``alembic downgrade base`` dependable.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

#: Documented SQLAlchemy naming convention. Every constraint the models
#: create gets a deterministic, table-scoped name.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Shared declarative base carrying the naming convention."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


__all__ = ["NAMING_CONVENTION", "Base"]
