"""Backup and restore, proved end to end on a throwaway database.

`docs/architecture/database.md` makes "backup and restore verified once, end
to end" an exit criterion for Phase 2. Before this file existed nothing in
the repository had ever taken a backup, so the criterion was simply unmet.

What it has to show:

* a backup contains the rows, not just a manifest claiming to;
* restoring into an empty database reproduces every row *exactly* - the
  comparison is the whole table, not a count;
* a sequence is re-aimed afterwards, so the next insert does not collide
  with a restored row. This is the part a naive COPY-based restore gets
  wrong, and the failure only shows up on the *next* write, which is why it
  is asserted rather than assumed;
* a restore into a database that already holds data is refused unless the
  caller asks for it, and a restore into a database at a different schema
  revision is refused outright.

Everything happens on `harsh_quant_os_backup_probe`, dropped before and
after. The name is checked against the configured database by
:func:`_db.url_for` before a connection is opened, so no edit to this file
can reach real data. The migration helpers are imported from
`test_migrations`, which is where the "build from empty" machinery already
lives; only the probe name differs.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from harsh_quant_os.auth import AuthService
from harsh_quant_os.cli import main
from harsh_quant_os.config import Settings
from harsh_quant_os.db import (
    AuditLog,
    BackupError,
    BackupManifest,
    UserSession,
    build_engine,
    build_session_factory,
    dispose_engine,
    export_database,
    import_database,
)
from harsh_quant_os.db.backup import MANIFEST_NAME

from ._db import maintenance_url, query, run_admin, url_for
from .test_migrations import _revision, _tables, _upgrade

#: The only database this file may ever write to.
PROBE_DATABASE_NAME = "harsh_quant_os_backup_probe"

#: Valid against the password policy so `create_user` reaches the database,
#: and under 24 characters so no secret scanner reads it as one.
PASSWORD = "quant-dev-passphrase"


@contextmanager
def _probe_database(live_settings: Settings) -> Iterator[str]:
    """Yield a freshly created probe database, and drop it either way.

    Dropped first as well as last, so a previous run that crashed before its
    own teardown cannot become this run's starting state.
    """
    probe = url_for(live_settings, PROBE_DATABASE_NAME)
    maintenance = maintenance_url(live_settings)
    _recreate_probe(maintenance)
    try:
        yield probe
    finally:
        run_admin(maintenance, f'DROP DATABASE IF EXISTS "{PROBE_DATABASE_NAME}" WITH (FORCE)')


def _recreate_probe(maintenance: str) -> None:
    """Drop the probe database if present and create it again, empty."""
    run_admin(maintenance, f'DROP DATABASE IF EXISTS "{PROBE_DATABASE_NAME}" WITH (FORCE)')
    run_admin(maintenance, f'CREATE DATABASE "{PROBE_DATABASE_NAME}"')


async def _seed(engine: AsyncEngine, live_settings: Settings) -> str:
    """One account, one session and three audit rows. Returns the address.

    Built through the real services rather than raw INSERTs, so what gets
    backed up is exactly what the application would have written.
    """
    service = AuthService(
        session_factory=build_session_factory(engine),
        secret_key=live_settings.auth_secret_key,
        session_ttl=timedelta(minutes=60),
    )
    email = f"backup-{uuid.uuid4().hex[:10]}@example.com"
    user = await service.create_user(email=email, password=PASSWORD)

    now = datetime.now(UTC)
    factory = build_session_factory(engine)
    async with factory() as session:
        session.add(
            UserSession(user_id=user.id, token_hash="a" * 64, expires_at=now + timedelta(hours=1))
        )
        for _ in range(3):
            session.add(
                AuditLog(
                    event_type="auth.login.succeeded",
                    outcome="success",
                    actor_email=email,
                    occurred_at=now,
                )
            )
        await session.commit()
    return email


async def _seed_and_export(url: str, live_settings: Settings, destination: Path) -> BackupManifest:
    """Seed and back up in one event loop, then let the engine go.

    An ``AsyncEngine`` pools connections bound to the loop that opened them,
    so every coroutine here builds its own engine and disposes of it before
    the loop closes. Two separate ``asyncio.run`` calls sharing one engine
    would hand the second loop a connection from the first.
    """
    engine = build_engine(url)
    try:
        await _seed(engine, live_settings)
        return await export_database(engine, destination)
    finally:
        await dispose_engine(engine)


async def _restore(url: str, source: Path, *, replace_existing: bool = False) -> BackupManifest:
    """Restore with its own engine, for the same loop-lifetime reason."""
    engine = build_engine(url)
    try:
        return await import_database(engine, source, replace_existing=replace_existing)
    finally:
        await dispose_engine(engine)


async def _export(url: str, destination: Path) -> BackupManifest:
    """Export with its own engine, for the same loop-lifetime reason."""
    engine = build_engine(url)
    try:
        return await export_database(engine, destination)
    finally:
        await dispose_engine(engine)


async def _seed_only(url: str, live_settings: Settings) -> None:
    """Populate the probe database without writing a backup."""
    engine = build_engine(url)
    try:
        await _seed(engine, live_settings)
    finally:
        await dispose_engine(engine)


def _snapshot(url: str) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table, ordered so two runs compare equal.

    Ordered by the first column, which is the primary key of every table in
    this schema - without an ORDER BY, comparing two reads of the same rows
    would be comparing the server's mood.
    """
    return {name: query(url, f'SELECT * FROM "{name}" ORDER BY 1') for name in sorted(_tables(url))}


@pytest.mark.integration
def test_a_backup_restores_every_row_and_keeps_writing(
    require_postgres: None, live_settings: Settings, tmp_path: Path
) -> None:
    """Export, rebuild from empty, import, and compare the whole database."""
    _ = require_postgres
    backup_dir = tmp_path / "backup"
    maintenance = maintenance_url(live_settings)

    with _probe_database(live_settings) as url:
        _upgrade(url)
        manifest = asyncio.run(_seed_and_export(url, live_settings, backup_dir))
        before = _snapshot(url)

        # The manifest is a claim; the files are the backup.
        assert (backup_dir / MANIFEST_NAME).is_file()
        assert manifest.schema_revision == _revision(url)
        for entry in manifest.tables:
            assert entry.rows > 0, f"{entry.name} was exported empty"
            assert (backup_dir / entry.file).stat().st_size > 0
        assert manifest.total_rows == sum(len(rows) for rows in before.values())

        # Rebuild the database the way a disaster would leave it: empty.
        # `alembic_version` is Alembic's own bookkeeping and is written by
        # the migration itself, so it is the one table that is not empty.
        _recreate_probe(maintenance)
        _upgrade(url)
        emptied = _snapshot(url)
        assert set(emptied) == set(before), "the rebuilt schema lost a table"
        for name, rows in emptied.items():
            if name != "alembic_version":
                assert rows == [], f"{name} still held rows before the restore"

        asyncio.run(_restore(url, backup_dir))
        after = _snapshot(url)

        assert after == before, "the restored database does not match the original"

        # Every row is back, so the sequence has to carry on after them.
        previous = max(int(row[0]) for row in before["audit_log"])
        query(
            url,
            "INSERT INTO audit_log (event_type, outcome) VALUES (:event, :outcome)",
            {"event": "auth.login.succeeded", "outcome": "success"},
        )
        created = int(query(url, "SELECT max(id) FROM audit_log")[0][0])
        assert created == previous + 1, (
            "the identity sequence was not advanced by the restore: the next insert "
            f"got {created}, expected {previous + 1}"
        )

        # And a second restore into a populated database has to be asked for.
        with pytest.raises(BackupError, match="replace_existing"):
            asyncio.run(_restore(url, backup_dir))


@pytest.mark.integration
def test_a_restore_refuses_a_database_it_could_silently_corrupt(
    require_postgres: None, live_settings: Settings, tmp_path: Path
) -> None:
    """Missing manifest and wrong schema revision are both hard refusals."""
    _ = require_postgres
    backup_dir = tmp_path / "refused"
    maintenance = maintenance_url(live_settings)

    with _probe_database(live_settings) as url:
        _upgrade(url)
        asyncio.run(_seed_and_export(url, live_settings, backup_dir))

        # (a) A directory without a manifest is not a backup.
        empty = tmp_path / "not-a-backup"
        empty.mkdir()
        with pytest.raises(BackupError, match=MANIFEST_NAME):
            asyncio.run(_restore(url, empty))

        # (b) A database that has never been migrated is at no revision, and
        #     the backup was taken at one. Loading anyway would put rows into
        #     a schema that cannot hold them.
        _recreate_probe(maintenance)
        with pytest.raises(BackupError, match="migrate"):
            asyncio.run(_restore(url, backup_dir))

        # (c) Export refuses to write over an existing backup.
        _upgrade(url)
        with pytest.raises(BackupError, match="not empty"):
            asyncio.run(_export(url, backup_dir))


@pytest.mark.integration
def test_the_cli_backs_up_and_restores_through_the_probe_database(
    require_postgres: None,
    live_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The commands an operator would actually type, run for real.

    A module with no way to reach it is not a script, so this drives
    ``hqos db backup`` and ``hqos db restore`` the same way a shell would -
    including the refusal when the target already holds data. ``DATABASE_URL``
    is pointed at the probe database for the duration, which is the only
    reason this test is allowed near a connection string at all: the CLI then
    reads it from the environment exactly as it would from ``.env``.
    """
    _ = require_postgres
    maintenance = maintenance_url(live_settings)

    with _probe_database(live_settings) as url:
        _upgrade(url)
        asyncio.run(_seed_only(url, live_settings))
        monkeypatch.setenv("DATABASE_URL", url)

        backup_dir = tmp_path / "cli-backup"
        assert main(["db", "backup", "--output", str(backup_dir)]) == 0
        backed_up = capsys.readouterr().out
        assert "backup written" in backed_up
        assert "users" in backed_up, "the summary did not name a table it wrote"
        assert (backup_dir / MANIFEST_NAME).is_file()

        # Rebuild empty, then put it back through the command.
        _recreate_probe(maintenance)
        _upgrade(url)
        capsys.readouterr()

        assert main(["db", "restore", "--source", str(backup_dir)]) == 0
        restored = capsys.readouterr().out
        assert "restore complete" in restored
        assert len(_snapshot(url)["users"]) == 1

        # A second restore has to be asked to discard what it would overwrite.
        assert main(["db", "restore", "--source", str(backup_dir)]) == 1
        refused = capsys.readouterr()
        assert "replace_existing" in refused.err

        # Nothing either command printed may carry the credential.
        credential = url.split("//", 1)[1].split("@", 1)[0].split(":", 1)[1]
        for name, secret in (
            ("the password", credential),
            ("a connection string", "postgresql"),
        ):
            assert secret not in backed_up + restored + refused.out + refused.err, (
                f"the CLI output contained {name}"
            )
