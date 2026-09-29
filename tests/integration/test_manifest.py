"""The manifest, written and read back against real PostgreSQL.

Phase 3's roadmap bullet is "quality status, provenance and version on
every stored dataset". The schema half of that is asserted in
``test_migrations.py``; this file covers the other half — that the code
actually writes those three facts, that a re-ingest updates one row rather
than creating a second dataset, and that every registration appends
provenance which the append-only trigger then refuses to revise.

Assertions are written so they hold on a second run against the same
database: the test database is never dropped, so counts of *other* rows
would be a claim about how many times somebody has run this suite. The
bars are local fixtures; nothing here is a price, a measurement or a
result.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harsh_quant_os.contracts.provenance import Timeframe
from harsh_quant_os.data import Bar, store_batch, validate_bars
from harsh_quant_os.data.manifest import dataset_by_name, register_dataset
from harsh_quant_os.db.models import Dataset, DatasetProvenance

ORIGIN = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
NAME = "phase3.manifest.probe"


def _minutes(count: int, *, offset: int = 0) -> list[Bar]:
    return [
        Bar(
            symbol="TEST.NEUTRAL",
            timeframe=Timeframe.M1,
            timestamp=ORIGIN + timedelta(minutes=index + offset),
            open=Decimal("100.00"),
            high=Decimal("101.25"),
            low=Decimal("99.75"),
            close=Decimal("100.50"),
            volume=Decimal("1000"),
        )
        for index in range(count)
    ]


async def _provenance_rows(
    session_factory: async_sessionmaker[AsyncSession], dataset_id: uuid.UUID
) -> list[DatasetProvenance]:
    async with session_factory() as session:
        result = await session.execute(
            select(DatasetProvenance).where(DatasetProvenance.dataset_id == dataset_id)
        )
        return list(result.scalars().all())


async def _dataset_row_count(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(Dataset).where(Dataset.name == NAME)
        )
    return int(count or 0)


async def test_a_stored_batch_records_status_version_and_provenance(
    require_postgres: None,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """The three facts phase 3 requires, read back after writing."""
    _ = require_postgres

    bars = _minutes(12)
    report = validate_bars(bars, timeframe=Timeframe.M1)
    stored = store_batch(tmp_path, name=NAME, source="unit", raw_bars=bars, report=report)

    dataset_id = await register_dataset(session_factory, stored)
    row = await dataset_by_name(session_factory, NAME)

    assert row is not None, "the manifest row was not written"
    assert row.id == dataset_id
    assert row.quality_status == report.status.value
    assert row.version == stored.version, "the manifest version is not the stored version"
    assert row.storage_path == stored.clean_path
    assert row.instrument == "TEST.NEUTRAL"
    assert row.timeframe == "1m"

    recorded = await _provenance_rows(session_factory, dataset_id)
    assert recorded, "no provenance row was appended"
    matching = [p for p in recorded if p.checksum_sha256 == stored.raw_sha256]
    assert matching, "no provenance row recorded this acquisition's raw artefact"

    acquisition = matching[0]
    assert acquisition.source == "unit"
    assert acquisition.row_count == stored.row_count
    assert acquisition.acquired_at.tzinfo is not None

    notes = acquisition.notes or ""
    assert "not checked:" in notes, f"the report's caveats were dropped: {notes!r}"


async def test_a_reingest_updates_one_row_and_appends_provenance(
    require_postgres: None,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Same logical dataset twice: one row, two acquisitions, no branching."""
    _ = require_postgres

    first_bars = _minutes(12)
    first = store_batch(
        tmp_path,
        name=NAME,
        source="unit",
        raw_bars=first_bars,
        report=validate_bars(first_bars, timeframe=Timeframe.M1),
    )
    first_id = await register_dataset(session_factory, first)
    before = len(await _provenance_rows(session_factory, first_id))

    # The identical batch again: nothing new is written to disk, but the
    # acquisition is still a real event and still gets recorded.
    await register_dataset(session_factory, first)
    assert await _dataset_row_count(session_factory) == 1, "a second dataset row appeared"
    assert len(await _provenance_rows(session_factory, first_id)) == before + 1

    # A different batch under the same name: the manifest follows the files
    # to the new version rather than being left describing the old ones.
    second_bars = _minutes(12, offset=500)
    second = store_batch(
        tmp_path,
        name=NAME,
        source="unit",
        raw_bars=second_bars,
        report=validate_bars(second_bars, timeframe=Timeframe.M1),
    )
    assert second.version != first.version

    second_id = await register_dataset(session_factory, second)

    assert second_id == first_id, "the same logical dataset got a second identity"
    assert await _dataset_row_count(session_factory) == 1

    row = await dataset_by_name(session_factory, NAME)
    assert row is not None
    assert row.version == second.version, "the manifest still points at the previous version"
    assert row.storage_path == second.clean_path
    assert len(await _provenance_rows(session_factory, first_id)) == before + 2


async def test_registering_does_not_get_around_the_append_only_rule(
    require_postgres: None,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """The manifest write must not have found a way past the trigger."""
    _ = require_postgres

    bars = _minutes(12)
    stored = store_batch(
        tmp_path,
        name=NAME,
        source="unit",
        raw_bars=bars,
        report=validate_bars(bars, timeframe=Timeframe.M1),
    )
    dataset_id = await register_dataset(session_factory, stored)
    assert await _provenance_rows(session_factory, dataset_id)

    with pytest.raises(Exception) as refused:
        async with session_factory() as session:
            await session.execute(text("UPDATE dataset_provenance SET row_count = 999999"))
            await session.commit()

    assert "append-only" in str(refused.value)
    assert all(
        p.row_count != 999999 for p in await _provenance_rows(session_factory, dataset_id)
    ), "the revision was applied"
