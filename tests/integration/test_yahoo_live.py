"""The adapter against Yahoo's real chart endpoint, end to end.

Skipped unless ``HQOS_LIVE_PROVIDER_TESTS=1``. A suite that reaches the
network on every run goes red for reasons nobody reading the failure can
fix, so this one is opt-in — and a skip is reported as a skip, never
counted as a pass.

The response shapes this adapter relies on came from probing the live
endpoint while the adapter was written, not from documentation: an
unknown symbol answers HTTP 404 with an empty body, intraday windows
beyond what the feed still holds answer 400/422 with empty bodies, and
``dataGranularity`` echoes the requested interval for every interval the
mapping supports. The assertions below check the properties those probes
made load-bearing — that the series arrives in the requested timeframe
with the caller's own symbol spelling and timezone-aware instants.

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
    BarRequest,
    UrllibTransport,
    YahooProvider,
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

NAME = "yahoo.live.probe"


async def test_a_live_nse_batch_lands_with_complete_provenance(
    require_postgres: None,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """One real fetch of NSE's index, carried to a registered manifest row."""
    _ = require_postgres

    provider = YahooProvider(UrllibTransport())
    fetched_at = datetime.now(tz=UTC)

    bars = await provider.latest_bars("^NSEI", Timeframe.D1)
    assert bars, "the live feed returned no bars"

    # Real data, not a cached fixture: everything asked for sits between
    # the moment of the call and 400 days back from it, and daily bars
    # carry a completed-day margin on top.
    oldest_allowed = fetched_at - timedelta(days=401)
    assert all(bar.timestamp >= oldest_allowed for bar in bars)
    assert all(bar.timestamp.tzinfo is not None for bar in bars)
    assert all(bar.symbol == "^NSEI" for bar in bars), "the caller's symbol spelling changed"
    assert all(bar.high >= bar.low for bar in bars)
    assert all(bar.close > Decimal("0") and bar.open > Decimal("0") for bar in bars), (
        "a live price did not read as a price"
    )
    assert all(bar.volume is None or bar.volume >= 0 for bar in bars)

    report = validate_bars(bars, timeframe=Timeframe.D1)
    assert report.status is not DataQualityStatus.INVALID, report.reasons
    assert report.accepted_bars, "validation accepted nothing from a live batch"

    stored = store_batch(
        tmp_path,
        name=NAME,
        source=provider.source,
        raw_bars=bars,
        report=report,
    )
    assert stored.row_count == len(report.accepted_bars)
    assert (tmp_path / stored.clean_path).is_file()
    assert (tmp_path / stored.raw_path).is_file()
    assert read_bars(tmp_path / stored.clean_path) == list(report.accepted_bars), (
        "the live bars did not survive the round trip digit for digit"
    )
    assert stored.instrument == "^NSEI", "provenance did not keep the provider's namespace"

    dataset_id = await register_dataset(session_factory, stored)
    row = await dataset_by_name(session_factory, NAME)
    assert row is not None, "the manifest row was not written"
    assert row.id == dataset_id
    assert row.quality_status == report.status.value
    assert row.version == stored.version, "the manifest version is not the stored version"
    assert row.storage_path == stored.clean_path
    assert row.instrument == "^NSEI"

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
    assert matching[0].source == provider.source, "provenance recorded a source the code did not"
    assert matching[0].row_count == stored.received


async def test_live_nse_and_bse_equity_symbols_answer_in_their_own_namespaces() -> None:
    """Both venues, both spellings, one company: ``TCS.NS`` and
    ``TCS.BO`` are the same issuer on two exchanges with two order
    books, and the adapter must keep them apart rather than quietly
    merge them into one series.

    A short daily window ending now: real sessions, real weekend gaps,
    and neither a claim about completeness beyond what was asked nor a
    database row — this test only proves the two namespaces answer.
    """
    provider = YahooProvider(UrllibTransport())
    start = datetime.now(tz=UTC) - timedelta(days=30)

    for symbol in ("TCS.NS", "TCS.BO"):
        bars = await provider.fetch_bars(
            BarRequest(symbol=symbol, timeframe=Timeframe.D1, start=start),
        )
        assert bars, f"{symbol}: the live feed returned no bars"
        assert all(bar.symbol == symbol for bar in bars), "the venue namespace was rewritten"
        assert all(bar.close > Decimal("0") for bar in bars)
        report = validate_bars(bars, timeframe=Timeframe.D1)
        assert report.status is not DataQualityStatus.INVALID, report.reasons
