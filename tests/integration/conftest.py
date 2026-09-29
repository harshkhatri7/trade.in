"""Fixtures for the tests that need a real PostgreSQL server.

Three rules this file exists to enforce:

1. **The development database is never touched.** Every connection URL comes
   from :func:`tests.integration._db.url_for`, which renames the configured
   database to ``harsh_quant_os_test`` and asserts the result *before* a
   connection is attempted. The configured database is read only to borrow
   its host, port and credential; no statement is ever executed against it.
2. **Absence of a server is never silent.** :func:`require_postgres` prints
   a reason and skips on a machine without Docker, and fails instead when
   ``HQOS_REQUIRE_POSTGRES=1`` - the flag CI sets, so a missing service there
   cannot be mistaken for a pass.
3. **Every test owns its own engine.** The engine is function-scoped and
   disposed at teardown, so no connection outlives the event loop it was
   created on.

The schema is brought to ``head`` once per session. Proving that the schema
can be built from *empty* - and taken back down again - is
``tests/integration/test_migrations.py``'s job, using its own throwaway
database; this fixture only guarantees a migrated database to run against.
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from harsh_quant_os.auth import AuthService
from harsh_quant_os.config import Settings
from harsh_quant_os.db import build_engine, build_session_factory, dispose_engine
from hqos_api.factory import create_app

from ._db import maintenance_url, run_admin, url_for

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The only database these fixtures may ever write to.
TEST_DATABASE_NAME = "harsh_quant_os_test"


def _listening(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def live_settings() -> Settings:
    """The repository's real configuration, read exactly as the API reads it.

    Used for its host, port and credential only. Nothing here is printed,
    and no URL in this module is ever rendered to text.
    """
    return Settings.load()


@pytest.fixture(scope="session")
def require_postgres(live_settings: Settings) -> None:
    """Gate every database-backed test on the server actually being there.

    Deliberately not silent: a run that quietly skipped its database tests
    would look identical to a run that passed them.
    """
    if _listening(live_settings.database_host, live_settings.database_port):
        return
    reason = (
        f"PostgreSQL is not listening on "
        f"{live_settings.database_host}:{live_settings.database_port}; "
        "this test needs a real server, not a substitute"
    )
    print(f"SKIPPED: {reason}", flush=True)
    if os.environ.get("HQOS_REQUIRE_POSTGRES") == "1":
        pytest.fail(f"{reason} (HQOS_REQUIRE_POSTGRES=1 forbids skipping)")
    pytest.skip(reason)


@pytest.fixture(scope="session")
def test_database_url(require_postgres: None, live_settings: Settings) -> str:
    """A migrated ``harsh_quant_os_test`` - never the configured database.

    ``url_for`` performs the never-the-configured-database assertion; this
    fixture's own job is only to make it exist and bring it to head. The
    database is created if it is missing but never dropped, because a
    session-scoped fixture that destroyed a database on teardown would have
    to be right about which one it was holding for the whole run.
    """
    _ = require_postgres
    url = url_for(live_settings, TEST_DATABASE_NAME)
    _ensure_database_exists(live_settings)
    _upgrade_to_head(url)
    return url


def _ensure_database_exists(live_settings: Settings) -> None:
    """Create ``harsh_quant_os_test`` if it is not there yet.

    ``CREATE DATABASE`` is refused inside a transaction, so the statement
    runs through :func:`_db.run_admin`, which is autocommit by construction.
    """
    maintenance = maintenance_url(live_settings)
    existing = run_admin(
        maintenance,
        "SELECT 1 FROM pg_database WHERE datname = :name",
        {"name": TEST_DATABASE_NAME},
    )
    if not existing:
        run_admin(maintenance, f'CREATE DATABASE "{TEST_DATABASE_NAME}"')


def _upgrade_to_head(url: str) -> None:
    """Apply every migration to ``url``.

    ``HQOS_DATABASE_URL`` is set for the duration and restored afterwards,
    because it is the first place ``alembic/env.py`` looks - a variable left
    behind would silently redirect every later migration in the session.
    """
    config = AlembicConfig()
    # In-memory rather than built from alembic.ini: env.py calls fileConfig()
    # whenever config_file_name is set, which would rewrite the logging tree
    # of the whole test session as a side effect of a fixture. The script
    # location is set explicitly, which also pins it to this repository
    # instead of the current working directory.
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    previous = os.environ.get("HQOS_DATABASE_URL")
    os.environ["HQOS_DATABASE_URL"] = url
    try:
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("HQOS_DATABASE_URL", None)
        else:
            os.environ["HQOS_DATABASE_URL"] = previous


@pytest.fixture
async def engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    """One connection pool per test, bound to that test's event loop."""
    created = build_engine(test_database_url)
    try:
        yield created
    finally:
        await dispose_engine(created)


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """The session maker the application service is built from."""
    yield build_session_factory(engine)


@pytest.fixture
async def auth_service(
    session_factory: async_sessionmaker[AsyncSession],
    live_settings: Settings,
) -> AsyncIterator[AuthService]:
    """A real :class:`AuthService` talking to real PostgreSQL."""
    yield AuthService(
        session_factory=session_factory,
        secret_key=live_settings.auth_secret_key,
        session_ttl=timedelta(minutes=live_settings.auth_token_expiry_minutes),
    )


@pytest.fixture
def app_settings(test_database_url: str) -> Settings:
    """Settings for an application that runs against the test database.

    ``_env_file=None`` keeps a developer's ``.env`` from changing what the
    suite asserts; only the database URL is carried over, and it is the one
    :func:`test_database_url` has already proved is not the configured
    database.
    """
    return Settings.load(_env_file=None, app_env="test", database_url=test_database_url)


@pytest.fixture
def client(app_settings: Settings) -> Iterator[TestClient]:
    """A ``TestClient`` whose lifespan has run against the test database.

    The lifespan is what builds the engine, the session factory and the auth
    service, so this is as close to a real process as a test can get without
    opening a port - and it exercises exactly the wiring the API ships with.
    """
    with TestClient(create_app(app_settings)) as test_client:
        yield test_client
