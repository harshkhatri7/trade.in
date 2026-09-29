"""Logical backup and restore of the metadata database.

Alembic can rebuild the schema from nothing, so what a backup has to preserve
is the part nothing else can recreate: the rows.

Each table moves through PostgreSQL's *binary* COPY (via asyncpg) rather than
through JSON or CSV. UUIDs, ``timestamptz``, ``numeric``, ``bytea`` and
``text`` then round-trip byte for byte, where a text format would have to
guess at timezone, locale and precision and would be wrong quietly.

Three rules the implementation keeps:

* **One snapshot.** Export and import each run inside a single transaction,
  so a backup cannot mix rows from either side of a concurrent write, and a
  restore that fails halfway leaves the database exactly as it was.
* **The schema revision travels with the rows.** The manifest records the
  Alembic revision the data was taken at, and a restore into a database at a
  different revision is refused rather than trusted. Loading rows written for
  one schema into another is how a backup corrupts a database politely.
* **Nothing is truncated without being asked.** A restore into a database
  that already holds rows requires ``replace_existing=True``.

What this is deliberately not: ``pg_dump``. It does not capture roles,
permissions, extensions or DDL (migrations own DDL), and it holds one table
at a time. That is the right trade for a metadata database and the wrong
trade for a data warehouse, which is why the distinction is written down
instead of assumed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

#: The file that makes a directory a backup. Written last on export, so an
#: interrupted export leaves a directory that cannot be mistaken for one.
MANIFEST_NAME = "manifest.json"

#: Bumped only when the on-disk layout changes incompatibly.
FORMAT_VERSION = 1

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_STATUS = re.compile(r"^COPY (\d+)$")


class BackupError(RuntimeError):
    """A backup or restore was refused for a reason the caller can fix."""


@dataclass(frozen=True)
class TableBackup:
    """One table inside a backup."""

    name: str
    file: str
    columns: tuple[str, ...]
    rows: int


@dataclass(frozen=True)
class BackupManifest:
    """What a backup contains, and the schema it was taken at."""

    format_version: int
    exported_at: str
    schema_revision: str | None
    tables: tuple[TableBackup, ...]

    @property
    def total_rows(self) -> int:
        """Rows in the whole backup, for a one-line summary."""
        return sum(table.rows for table in self.tables)

    def to_json(self) -> str:
        """Render the manifest, stable enough to be diffed or committed."""
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, payload: str) -> BackupManifest:
        """Read a manifest, refusing anything unrecognised."""
        try:
            raw: dict[str, Any] = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise BackupError(f"{MANIFEST_NAME} is not valid JSON: {exc}") from exc
        try:
            tables = tuple(
                TableBackup(
                    name=str(entry["name"]),
                    file=str(entry["file"]),
                    columns=tuple(str(column) for column in entry["columns"]),
                    rows=int(entry["rows"]),
                )
                for entry in raw["tables"]
            )
            schema_revision = raw["schema_revision"]
            return cls(
                format_version=int(raw["format_version"]),
                exported_at=str(raw["exported_at"]),
                schema_revision=None if schema_revision is None else str(schema_revision),
                tables=tables,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BackupError(f"{MANIFEST_NAME} is missing a required field: {exc}") from exc


def _require_identifier(name: str) -> str:
    """Accept only a plain identifier, because these are interpolated into DDL.

    The values come from PostgreSQL's catalog rather than from a caller, but
    catalog values are still checked rather than trusted: a name that would
    need quoting here would silently change meaning in the statement below.
    """
    if not _IDENTIFIER.match(name):
        raise BackupError(f"refusing to use {name!r} as a table or column name")
    return name


def _row_count(status: Any) -> int:
    """Turn asyncpg's ``COPY 12`` status into a number, or complain."""
    match = _STATUS.match(str(status))
    if match is None:
        raise BackupError(f"unexpected COPY status: {status!r}")
    return int(match.group(1))


async def _scalar(connection: AsyncConnection, statement: str, **params: Any) -> Any:
    """One value from one statement, so callers never touch a Result twice."""
    result = await connection.execute(text(statement), params)
    return result.scalar()


async def _driver(connection: AsyncConnection) -> Any:
    """The raw asyncpg connection underneath this SQLAlchemy connection.

    COPY is a streaming protocol operation: there is no way to express it as
    a parameterised ``execute``, and reading every row into Python first would
    make a backup's memory use proportional to the table. Going one layer
    down keeps that streaming, on the connection SQLAlchemy is already
    transacting on, so the copy is part of the same snapshot.
    """
    raw = await connection.get_raw_connection()
    driver = raw.driver_connection
    module = driver.__class__.__module__
    if not module.startswith("asyncpg"):
        raise BackupError(
            "backup uses PostgreSQL's binary COPY, which only asyncpg provides; "
            f"the driver in use is {module}"
        )
    return driver


async def _tables(connection: AsyncConnection) -> list[str]:
    """Every base table in ``public``, in a stable order."""
    result = await connection.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        )
    )
    return [str(row[0]) for row in result.all()]


async def _columns(connection: AsyncConnection, table: str) -> list[str]:
    """A table's columns in ordinal order - the order COPY has to see."""
    _require_identifier(table)
    result = await connection.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table "
            "ORDER BY ordinal_position"
        ),
        {"table": table},
    )
    columns = [str(row[0]) for row in result.all()]
    if not columns:
        raise BackupError(f"table {table!r} has no columns, so there is nothing to copy")
    return columns


async def _schema_revision(connection: AsyncConnection) -> str | None:
    """The Alembic revision this database is at, or ``None`` if un-migrated."""
    exists = await _scalar(connection, "SELECT to_regclass('public.alembic_version')")
    if exists is None:
        return None
    value = await _scalar(connection, "SELECT version_num FROM alembic_version")
    return None if value is None else str(value)


async def _parents(connection: AsyncConnection) -> dict[str, set[str]]:
    """Foreign keys as ``child -> {parents}``, so restore order can respect them."""
    result = await connection.execute(
        text(
            "SELECT tc.table_name AS child, ccu.table_name AS parent "
            "FROM information_schema.table_constraints AS tc "
            "JOIN information_schema.key_column_usage AS kcu "
            "  ON kcu.constraint_name = tc.constraint_name "
            " AND kcu.table_schema = tc.table_schema "
            "JOIN information_schema.constraint_column_usage AS ccu "
            "  ON ccu.constraint_name = tc.constraint_name "
            " AND ccu.table_schema = tc.table_schema "
            "WHERE tc.constraint_type = 'FOREIGN KEY' "
            "AND tc.table_schema = 'public' AND ccu.table_schema = 'public'"
        )
    )
    mapping: dict[str, set[str]] = {}
    for child, parent in result.all():
        mapping.setdefault(str(child), set()).add(str(parent))
    return mapping


async def _identity_columns(connection: AsyncConnection, table: str) -> list[str]:
    """Columns whose sequence has to be re-aimed after a restore."""
    _require_identifier(table)
    result = await connection.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table "
            "AND (is_identity = 'YES' OR column_default LIKE 'nextval(%') "
            "ORDER BY ordinal_position"
        ),
        {"table": table},
    )
    return [str(row[0]) for row in result.all()]


def _restore_order(tables: Sequence[str], parents: Mapping[str, set[str]]) -> list[str]:
    """Tables in an order a foreign key can be satisfied by.

    A row in ``sessions`` needs its ``users`` row to exist first, so parents
    are emitted before children. A cycle would make that impossible, and is
    reported instead of guessed at.
    """
    remaining = set(tables)
    ordered: list[str] = []
    while remaining:
        ready = sorted(name for name in remaining if not (parents.get(name, set()) & remaining))
        if not ready:
            cycle = ", ".join(sorted(remaining))
            raise BackupError(f"foreign keys form a cycle, so no restore order exists: {cycle}")
        ordered.extend(ready)
        remaining.difference_update(ready)
    return ordered


async def export_database(
    engine: AsyncEngine, destination: Path | str, *, overwrite: bool = False
) -> BackupManifest:
    """Write every table in ``engine``'s database to ``destination``.

    The directory is left without a manifest if anything fails part way, so a
    half-written export cannot be restored later by accident.
    """
    target = Path(destination)
    if target.exists() and any(target.iterdir()) and not overwrite:
        raise BackupError(
            f"{target} is not empty; refusing to overwrite an existing backup unless overwrite=True"
        )
    target.mkdir(parents=True, exist_ok=True)

    entries: list[TableBackup] = []
    async with engine.begin() as connection:
        revision = await _schema_revision(connection)
        driver = await _driver(connection)
        for table in await _tables(connection):
            columns = await _columns(connection, table)
            file_name = f"{table}.bin"
            status = await driver.copy_from_table(
                table,
                output=str(target / file_name),
                format="binary",
                columns=columns,
            )
            entries.append(
                TableBackup(
                    name=table,
                    file=file_name,
                    columns=tuple(columns),
                    rows=_row_count(status),
                )
            )

    manifest = BackupManifest(
        format_version=FORMAT_VERSION,
        exported_at=datetime.now(UTC).isoformat(),
        schema_revision=revision,
        tables=tuple(entries),
    )
    (target / MANIFEST_NAME).write_text(manifest.to_json(), encoding="utf-8")
    return manifest


async def import_database(
    engine: AsyncEngine, source: Path | str, *, replace_existing: bool = False
) -> BackupManifest:
    """Load a backup written by :func:`export_database` into ``engine``.

    Runs in one transaction: either every table and every sequence is
    restored, or none of it is.
    """
    directory = Path(source)
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.is_file():
        raise BackupError(f"{directory} contains no {MANIFEST_NAME}, so it is not a backup")
    manifest = BackupManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    if manifest.format_version != FORMAT_VERSION:
        raise BackupError(
            f"backup format {manifest.format_version} is not supported by format {FORMAT_VERSION}"
        )
    for entry in manifest.tables:
        _require_identifier(entry.name)
        if not (directory / entry.file).is_file():
            raise BackupError(f"the backup is missing {entry.file}")

    async with engine.begin() as connection:
        current = await _schema_revision(connection)
        if current != manifest.schema_revision:
            raise BackupError(
                f"the database is at schema revision {current!r} but the backup was "
                f"taken at {manifest.schema_revision!r}; migrate first so the rows "
                "match the schema they were written for"
            )

        present = set(await _tables(connection))
        missing = [entry.name for entry in manifest.tables if entry.name not in present]
        if missing:
            raise BackupError(
                "the backup holds tables this database does not have: "
                + ", ".join(sorted(missing))
                + "; run the migrations first"
            )

        if not replace_existing:
            for entry in manifest.tables:
                if entry.name == "alembic_version":
                    # Alembic writes this row the moment the schema is built,
                    # so its presence says nothing about whether the database
                    # holds data that would be discarded. It is still restored
                    # below; only the safety check skips it.
                    continue
                count = await _scalar(connection, f'SELECT count(*) FROM "{entry.name}"')
                if count and int(count) > 0:
                    raise BackupError(
                        f"{entry.name} already holds {count} rows; pass "
                        "replace_existing=True to discard them"
                    )

        tables = [entry.name for entry in manifest.tables]
        by_name = {entry.name: entry for entry in manifest.tables}
        order = _restore_order(tables, await _parents(connection))

        driver = await _driver(connection)
        if tables:
            truncated = ", ".join(f'"{name}"' for name in tables)
            # TRUNCATE bypasses the audit_log row trigger by design - it is
            # the same operator path `tests/integration/test_migrations.py`
            # documents - and its own append-only rule is about UPDATE and
            # DELETE of individual rows, not about restoring history.
            await connection.execute(text(f"TRUNCATE TABLE {truncated}"))

        for name in order:
            entry = by_name[name]
            status = await driver.copy_to_table(
                entry.name,
                source=str(directory / entry.file),
                format="binary",
                columns=list(entry.columns),
            )
            restored = _row_count(status)
            if restored != entry.rows:
                raise BackupError(
                    f"{entry.name}: the manifest records {entry.rows} rows but the "
                    f"restore copied {restored}"
                )

        # COPY does not advance sequences, so without this the next insert
        # would collide with a row that was just restored.
        for name in order:
            for column in await _identity_columns(connection, name):
                _require_identifier(column)
                highest = await _scalar(connection, f'SELECT max("{column}") FROM "{name}"')
                restart = 1 if highest is None else int(highest) + 1
                await connection.execute(
                    text(f'ALTER TABLE "{name}" ALTER COLUMN "{column}" RESTART WITH {restart}')
                )

    return manifest


__all__ = [
    "FORMAT_VERSION",
    "MANIFEST_NAME",
    "BackupError",
    "BackupManifest",
    "TableBackup",
    "export_database",
    "import_database",
]
