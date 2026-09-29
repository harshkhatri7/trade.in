"""The adapter against Kraken's real public endpoint, end to end.

Skipped unless ``HQOS_LIVE_PROVIDER_TESTS=1``. A suite that reaches the
network on every run goes red for reasons nobody reading the failure can
fix, so this one is opt-in — and a skip is reported as a skip, never
counted as a pass. When it runs it performs the whole of Phase 3 on live
public data: fetch, validate, write the artefacts, register the manifest.

The candle field order this adapter relies on came from Kraken's own
documentation while the adapter was written, and the live endpoint was
probed for its error responses: an unknown pair and an invalid interval
both answer HTTP 200 with an ``error`` array rather than an HTTP status.

Nothing asserted here is a price presented as a result, a performance
figure or a claim about anything a strategy might do. The bars written
below land in a temporary directory and a throwaway row in the test
database, with provenance recording where they came from — which is the
thing being checked.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harsh_quant_os.contracts.provenance import DataQualityStatus, Timeframe
from harsh_quant_os.data import (
    KrakenProvider,
    UrllibTransport,
    read_bars,
    store_batch,
    validate_bars,
)
from harsh_quant_os.data.manifest import dataset_by_name, register_dataset
from harsh_quant_os.db.models import DatasetProvenance

LIVE = os.environ.get("HQOS_LIVE_PROVIDER_TESTS") == "1"

pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="live provider tests are opt-in: set HQOS_LIVE_PROVIDER_TESTS=1",
)

NAME = "kraken.live.probe"
SOURCE = "https://api.kraken.com/0/public/OHLC"


async def test_a_live_batch_lands_with_complete_provenance(
    require_postgres: None,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """One real fetch, carried all the way to a registered manifest row."""
    _ = require_postgres

    provider = KrakenProvider(UrllibTransport())
    fetched_at = datetime.now(tz=UTC)

    bars = await provider.latest_bars("XBTUSD", Timeframe.H1)
    assert bars, "the live feed returned no committed candles"

    # Real data, not a cached fixture: everything asked for sits between
    # the moment of the call and one provider page back from it.
    oldest_allowed = fetched_at - timedelta(hours=721)
    assert all(bar.timestamp >= oldest_allowed for bar in bars)
    assert all(bar.timestamp.tzinfo is not None for bar in bars)
    assert all(bar.high >= bar.low for bar in bars)
    assert all(bar.close > Decimal("0") and bar.open > Decimal("0") for bar in bars), (
        "a live price did not read as a price"
    )

    report = validate_bars(bars, timeframe=Timeframe.H1)
    assert report.status is not DataQualityStatus.INVALID, report.reasons
    assert report.accepted_bars, "validation accepted nothing from a live batch"

    stored = store_batch(
        tmp_path,
        name=NAME,
        source=SOURCE,
        raw_bars=bars,
        report=report,
    )
    assert stored.row_count == len(report.accepted_bars)
    assert (tmp_path / stored.clean_path).is_file()
    assert (tmp_path / stored.raw_path).is_file()
    assert read_bars(tmp_path / stored.clean_path) == list(report.accepted_bars), (
        "the live bars did not survive the round trip digit for digit"
    )

    dataset_id = await register_dataset(session_factory, stored)
    row = await dataset_by_name(session_factory, NAME)
    assert row is not None, "the manifest row was not written"
    assert row.id == dataset_id
    assert row.quality_status == report.status.value
    assert row.version == stored.version, "the manifest version is not the stored version"
    assert row.storage_path == stored.clean_path

    async with session_factory() as session:
        recorded = list(
            (
                await session.execute(
                    select(DatasetProvenance).where(DatasetProvenance.dataset_id == dataset_id)
                )
            )
            .scalars()
            .all()
        )
    matching = [entry for entry in recorded if entry.checksum_sha256 == stored.raw_sha256]
    assert matching, "no provenance row carries this acquisition's checksum"
    assert matching[0].source == SOURCE
    assert matching[0].row_count == stored.received
