"""Shared database helpers for the integration suite.

Three things live here because getting any of them wrong is silent and
expensive, and duplication would let two copies drift:

* :func:`dsn` - rendering a connection string *with* its credential. This is
  the one place that must not use ``str(url)``, because SQLAlchemy masks the
  password there: an engine built from the masked form authenticates with
  ``***`` and reports a baffling "password authentication failed".
* :func:`url_for` - the safety assertion that keeps every helper in this
  suite off the configured database. It asserts the requested database name
  differs from the configured one *before* anything connects.
* :func:`run_admin` - statements PostgreSQL refuses inside a transaction
  (``CREATE DATABASE``, ``DROP DATABASE``), run with autocommit.

Nothing here prints, logs or formats a URL: these values are credentials,
and they are passed straight to the engine and discarded.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from harsh_quant_os.config import Settings
from harsh_quant_os.db import build_engine, dispose_engine

#: Database identifiers this suite is willing to interpolate into DDL.
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

#: The maintenance database used to create and drop other databases.
MAINTENANCE_DATABASE = "postgres"


def dsn(url: URL) -> str:
    """Render ``url`` as a connection string that actually authenticates.

    Deliberately not ``str(url)``: SQLAlchemy masks the password in ``str()``
    and in ``render_as_string()``'s default. That is right for a log line and
    wrong for a connection - the server would be handed ``***``. The result
    goes to ``build_engine`` or to Alembic's environment variable only, and
    is never printed.
    """
    return url.render_as_string(hide_password=False)


def url_for(live_settings: Settings, database: str) -> str:
    """A connection string for ``database``, asserted never to be the real one.

    This is the single choke point for that assertion: any helper that
    derives a new database from the configured one goes through here, so an
    edit cannot quietly start issuing statements against development data.
    """
    assert NAME_PATTERN.match(database), f"unsafe database name: {database!r}"
    configured = make_url(live_settings.database_url)
    assert configured.database != database, (
        "this suite only ever builds a destructive lifecycle around its own "
        f"database; the configured one is {configured.database!r} and must "
        "not be it"
    )
    return dsn(configured.set(database=database))


def maintenance_url(live_settings: Settings) -> str:
    """Connection string for the maintenance database."""
    return url_for(live_settings, MAINTENANCE_DATABASE)


def run_admin(
    url: str, statement: str, params: dict[str, Any] | None = None
) -> list[tuple[Any, ...]]:
    """Run ``statement`` with autocommit and return its rows.

    ``CREATE DATABASE`` and ``DROP DATABASE`` are refused inside a
    transaction, so this one engine is deliberately built with
    ``isolation_level="AUTOCOMMIT"`` rather than through ``build_engine``.
    The connection is private and disposed either way, so a statement that
    fails leaves nothing poisoned behind.
    """

    async def _run() -> list[tuple[Any, ...]]:
        engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as connection:
                result = await connection.execute(text(statement), params or {})
                return [tuple(row) for row in result.all()] if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(_run())


async def rows(
    engine: AsyncEngine, statement: str, params: dict[str, Any] | None = None
) -> list[tuple[Any, ...]]:
    """Run ``statement`` on ``engine`` and return its rows.

    For async tests that already hold an engine for their own event loop;
    the connection is opened and closed here so a failing assertion leaves
    no transaction open behind it.
    """
    async with engine.connect() as connection:
        result = await connection.execute(text(statement), params or {})
        fetched = [tuple(row) for row in result.all()] if result.returns_rows else []
        # Committed on purpose: the statement may be a write (the migration
        # tests insert an audit row before trying to rewrite it), and an
        # uncommitted write would vanish when this connection closes and
        # leave the next assertion reading stale state.
        await connection.commit()
        return fetched


def query(url: str, statement: str, params: dict[str, Any] | None = None) -> list[tuple[Any, ...]]:
    """Run ``statement`` against ``url`` and return its rows.

    The synchronous counterpart of :func:`rows`, for tests that are not
    themselves async. The engine is built per call and disposed in
    ``finally``: a test that fails mid-statement must not leave a
    transaction open for the next one.
    """

    async def _run() -> list[tuple[Any, ...]]:
        engine = build_engine(url)
        try:
            return await rows(engine, statement, params)
        finally:
            await dispose_engine(engine)

    return asyncio.run(_run())
