"""Migration lifecycle, proven against a throwaway database.

``docs/architecture/database.md`` promises that Phase 2 runs migrations from
empty on every pull request. This file is that promise made executable:

* the schema builds from a database that has no tables at all;
* ``downgrade base`` removes everything the migration created - the one
  survivor is ``alembic_version``, which is Alembic's own bookkeeping and
  has no migration that drops it;
* upgrading again afterwards works;
* ``audit_log`` accepts inserts but refuses UPDATE and DELETE *at the
  database*, carrying the trigger's own message as proof that the trigger
  was what refused, and TRUNCATE still works for operator tooling;
* the constraints the design relies on are actually present - including the
  deliberate absence of foreign keys on ``audit_log``.

Everything happens on ``harsh_quant_os_migration_probe``, dropped before and
after. The name is checked against the configured database by
:func:`_db.url_for` before a connection is opened, so no edit to this file
can reach real data.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory

from harsh_quant_os.config import Settings

from ._db import maintenance_url, query, run_admin, url_for

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The only database this file may ever write to.
PROBE_DATABASE_NAME = "harsh_quant_os_migration_probe"

#: Tables the initial Phase 2 migration must leave behind.
EXPECTED_TABLES = {"alembic_version", "users", "sessions", "audit_log"}

#: The exact wording of the append-only trigger's refusal. Asserting it is
#: how the test proves *the trigger* refused, rather than some incidental
#: constraint or a connection that happened to break.
APPEND_ONLY_MESSAGE = "audit_log is append-only"


def _alembic_config() -> AlembicConfig:
    """An in-memory Alembic config.

    Deliberately not built from ``alembic.ini``: ``env.py`` calls
    ``fileConfig()`` whenever ``config_file_name`` is set, which would
    reconfigure the *whole* logging tree as a side effect of a test and
    change what unrelated tests observe. The script location is set
    explicitly instead, which also makes this independent of the working
    directory.
    """
    config = AlembicConfig()
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return config


@contextmanager
def _pointed_at(url: str) -> Iterator[None]:
    """Point ``alembic/env.py`` at ``url``, and put the variable back."""
    previous = os.environ.get("HQOS_DATABASE_URL")
    os.environ["HQOS_DATABASE_URL"] = url
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("HQOS_DATABASE_URL", None)
        else:
            os.environ["HQOS_DATABASE_URL"] = previous


def _upgrade(url: str) -> None:
    with _pointed_at(url):
        command.upgrade(_alembic_config(), "head")


def _downgrade(url: str) -> None:
    with _pointed_at(url):
        command.downgrade(_alembic_config(), "base")


def _head_revision() -> str:
    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    assert head is not None, "the migration directory has no head revision"
    return head


@contextmanager
def _probe_database(live_settings: Settings) -> Iterator[str]:
    """Yield a freshly created probe database, and drop it either way.

    Dropped first as well as last so that a previous run which crashed
    before its own teardown does not become this run's starting state -
    otherwise "builds from empty" would silently degrade into "reuses
    whatever was left".
    """
    probe = url_for(live_settings, PROBE_DATABASE_NAME)
    maintenance = maintenance_url(live_settings)
    run_admin(maintenance, f'DROP DATABASE IF EXISTS "{PROBE_DATABASE_NAME}" WITH (FORCE)')
    run_admin(maintenance, f'CREATE DATABASE "{PROBE_DATABASE_NAME}"')
    try:
        yield probe
    finally:
        run_admin(maintenance, f'DROP DATABASE IF EXISTS "{PROBE_DATABASE_NAME}" WITH (FORCE)')


def _tables(url: str) -> set[str]:
    rows = query(
        url,
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'",
    )
    return {str(row[0]) for row in rows}


def _revision(url: str) -> str | None:
    rows = query(url, "SELECT version_num FROM alembic_version")
    return str(rows[0][0]) if rows else None


def _sqlstate(exc: BaseException) -> str | None:
    """The PostgreSQL SQLSTATE carried by an exception, when there is one."""
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        for candidate in (current, getattr(current, "orig", None)):
            if candidate is None:
                continue
            for attribute in ("sqlstate", "pgcode"):
                value = getattr(candidate, attribute, None)
                if value:
                    return str(value)
        for related in (
            getattr(current, "orig", None),
            current.__cause__,
            current.__context__,
        ):
            if related is not None and id(related) not in seen:
                stack.append(related)
    return None


@pytest.mark.integration
def test_schema_builds_from_empty_and_tears_down_again(
    require_postgres: None, live_settings: Settings
) -> None:
    """Upgrade from nothing, downgrade to nothing, upgrade again."""
    _ = require_postgres

    with _probe_database(live_settings) as url:
        assert _tables(url) == set(), "the probe database must start with no tables"

        _upgrade(url)
        assert _tables(url) >= EXPECTED_TABLES
        assert _revision(url) == _head_revision(), "the schema is not at head after upgrade"

        _downgrade(url)
        # `alembic_version` is Alembic's own bookkeeping: no migration drops
        # it, so an empty row set is what "everything was reversed" means.
        assert _tables(url) == {"alembic_version"}, "downgrade left application tables behind"
        assert _revision(url) is None, "downgrade left a revision recorded"

        _upgrade(url)
        assert _tables(url) >= EXPECTED_TABLES
        assert _revision(url) == _head_revision()


@pytest.mark.integration
def test_audit_log_refuses_update_and_delete(
    require_postgres: None, live_settings: Settings
) -> None:
    """Immutability is enforced by PostgreSQL, not by the application."""
    _ = require_postgres

    with _probe_database(live_settings) as url:
        _upgrade(url)

        query(
            url,
            "INSERT INTO audit_log (event_type, outcome) VALUES (:event, :outcome)",
            {"event": "auth.login.succeeded", "outcome": "success"},
        )
        assert query(url, "SELECT count(*) FROM audit_log") == [(1,)]

        with pytest.raises(Exception) as update:
            query(url, "UPDATE audit_log SET detail = 'rewritten'")
        assert APPEND_ONLY_MESSAGE in str(update.value)
        assert _sqlstate(update.value) == "42501", "the refusal was not a privilege error"
        assert query(url, "SELECT detail FROM audit_log") == [(None,)]

        with pytest.raises(Exception) as delete:
            query(url, "DELETE FROM audit_log")
        assert APPEND_ONLY_MESSAGE in str(delete.value)
        assert _sqlstate(delete.value) == "42501", "the refusal was not a privilege error"
        assert query(url, "SELECT count(*) FROM audit_log") == [(1,)]

        # TRUNCATE bypasses row triggers by design: it is the operator and
        # test-tooling path, and stating it here keeps that an explicit
        # choice rather than an unnoticed hole.
        query(url, "TRUNCATE TABLE audit_log")
        assert query(url, "SELECT count(*) FROM audit_log") == [(0,)]


@pytest.mark.integration
def test_schema_has_the_constraints_the_design_depends_on(
    require_postgres: None, live_settings: Settings
) -> None:
    """Foreign keys where they matter, none where they would be a hazard."""
    _ = require_postgres

    with _probe_database(live_settings) as url:
        _upgrade(url)

        session_keys = query(
            url,
            """
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'sessions'::regclass AND contype = 'f'
            """,
        )
        assert session_keys, "sessions.user_id must reference users.id"

        audit_keys = query(
            url,
            """
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'audit_log'::regclass AND contype = 'f'
            """,
        )
        assert audit_keys == [], (
            "audit_log must have no foreign keys: a cascading delete would "
            "silently rewrite an immutable record"
        )

        audit_checks = query(
            url,
            """
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'audit_log'::regclass AND contype = 'c'
            ORDER BY conname
            """,
        )
        # Names are SQLAlchemy's (``ck_<table>_<name>``); pinning them here
        # means a rename shows up as a failing test rather than as a
        # constraint nobody noticed had gone missing.
        assert [row[0] for row in audit_checks] == [
            "ck_audit_log_actor_email_lowercase",
            "ck_audit_log_event_type",
            "ck_audit_log_outcome",
        ]

        triggers = query(
            url,
            "SELECT tgname FROM pg_trigger WHERE tgrelid = 'audit_log'::regclass",
        )
        assert [row[0] for row in triggers] == ["audit_log_append_only"]

        unique_email = query(
            url,
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'users' AND indexdef ILIKE '%UNIQUE%'
            """,
        )
        assert unique_email, "users.email must be unique"

        unique_token = query(
            url,
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'sessions' AND indexdef ILIKE '%UNIQUE%'
            """,
        )
        assert unique_token, "sessions.token_hash must be unique"


@pytest.mark.integration
def test_models_and_migration_have_not_drifted(
    require_postgres: None, live_settings: Settings
) -> None:
    """The ORM metadata and the applied schema describe the same database.

    A migration that is out of date with its models passes every other test
    in this file - the tables exist and the constraints are there - while
    still being wrong for the next deploy. Autogenerate is asked what it
    would change, and the answer has to be nothing.
    """
    import asyncio

    from alembic.autogenerate import produce_migrations
    from alembic.migration import MigrationContext
    from sqlalchemy import Connection

    from harsh_quant_os.db import Base, build_engine, dispose_engine

    _ = require_postgres

    with _probe_database(live_settings) as url:
        _upgrade(url)

        async def _compare() -> list[Any]:
            engine = build_engine(url)
            try:
                async with engine.connect() as connection:

                    def _generate(sync_connection: Connection) -> Any:
                        context = MigrationContext.configure(
                            sync_connection,
                            opts={
                                "compare_type": True,
                                "compare_server_default": True,
                            },
                        )
                        return produce_migrations(context, Base.metadata)

                    migration = await connection.run_sync(_generate)
                return list(migration.upgrade_ops.ops)
            finally:
                await dispose_engine(engine)

        unexpected: list[Any] = asyncio.run(_compare())
        assert unexpected == [], (
            "the applied schema no longer matches the models; run "
            "`python -m alembic revision --autogenerate` and commit the result"
        )
