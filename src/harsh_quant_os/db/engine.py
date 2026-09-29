"""Async engine and session factories.

One rule governs this module: **the connection string never appears in a
log line, an exception message it constructs, or a printed diagnostic.**
The DSN carries the database password, so it is treated as a credential -
the engine is created, used and disposed, but never rendered to text.

Factories take an explicit URL rather than a :class:`Settings` so that a test
can point the identical code path at a throwaway database. Nothing here is a
module-level singleton: the caller owns the engine and disposes it, which is
what lets one process run the application and its integration tests against
different databases without either noticing the other.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)

__all__ = [
    "build_engine",
    "build_session_factory",
    "dispose_engine",
    "ping_database",
]


def build_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create an async engine for ``database_url``.

    ``pool_pre_ping`` issues a lightweight round trip before a pooled
    connection is handed out, so a connection PostgreSQL closed while the API
    was idle surfaces as a retryable failure instead of a confusing error
    halfway through a request.
    """
    if not database_url:
        raise ValueError("database_url is required")
    return create_async_engine(database_url, echo=echo, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Bind a session factory to ``engine``.

    ``expire_on_commit=False`` keeps attribute access valid after a commit,
    which matters because services commit inside a transaction and the router
    then reads the result; without it every read after commit raises on an
    expired instance.
    """
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def ping_database(engine: AsyncEngine) -> bool:
    """Return ``True`` when the database answers a trivial round trip.

    Never raises: readiness must be able to *report* an outage rather than
    turn into one. The exception class is logged, never the message, because
    a driver message can embed the connection string.
    """
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except Exception as exc:
        logger.warning("database.ping failed error_type=%s", type(exc).__name__)
        return False
    return True


async def dispose_engine(engine: AsyncEngine) -> None:
    """Close the engine's pool. Safe to call twice."""
    await engine.dispose()
