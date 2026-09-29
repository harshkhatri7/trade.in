"""Alembic migration environment.

Async by design: the project's only PostgreSQL driver is ``asyncpg``, which
has no DBAPI ``connect()``, so the synchronous template would not work at all.

The URL is resolved here rather than in ``alembic.ini`` so that:

* no credential is ever written to a tracked file;
* a test or CI job can point the *same* migration code path at a throwaway
  database by exporting ``HQOS_DATABASE_URL``, which is how "migrations run
  from empty" is proven without touching development data.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from harsh_quant_os.config import Settings, SettingsError
from harsh_quant_os.db import Base

# Importing Base from the package runs `harsh_quant_os.db.__init__`, which
# imports every model. Autogenerate compares live schema against
# `Base.metadata`; if that import were skipped the metadata would be empty
# and the generator would silently propose dropping everything.
config = context.config

# `disable_existing_loggers=False`: migrations are also run in-process by the
# test suite, and wiping the host application's loggers would be a hostile
# side effect for a schema tool to have.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _resolve_url() -> str:
    """Return the URL to migrate, or exit with an actionable message."""
    override = os.environ.get("HQOS_DATABASE_URL", "").strip()
    if override:
        return override
    try:
        return Settings.load().database_url
    except SettingsError:
        # The exception message is not interpolated on purpose: a settings
        # validation error can quote the offending value, and the offending
        # value here can be a credential. The type is enough to act on.
        raise SystemExit(
            "alembic: no database URL available.\n"
            "  Set HQOS_DATABASE_URL, or provision the local environment with\n"
            "  `npm run env:provision` so that Settings can read .env."
        ) from None


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (``alembic upgrade --sql``)."""
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations against an established connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Open an async connection, migrate, and always release the pool."""
    engine = create_async_engine(_resolve_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    """Run migrations against the configured database."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(run_async_migrations())
        return
    # A coroutine cannot be started on a loop that is already running, and
    # silently nesting event loops would be worse than saying so. Callers
    # inside async code should run this from a worker thread or from a sync
    # fixture instead.
    raise RuntimeError(
        "alembic was invoked from inside a running event loop; run migrations "
        "from synchronous code (the CLI, or a synchronous fixture)."
    )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
