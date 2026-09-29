"""Integration: a real store, a real manifest row, read over a real socket.

The subject of this file is the traceability claim itself. Every layer is
the one the platform ships:

* the store writes the artefact through :func:`store_batch`;
* the manifest row and its provenance are written by
  :func:`~harsh_quant_os.data.manifest.register_dataset`;
* a genuine uvicorn process serves them;
* a real HTTP client reads them back and validates the bytes against the
  shared contract.

Seeding copies the first three bars the observed ``hqos data ingest`` run
recorded (see ``docs/PROJECT-STATUS.md``), rather than reading ``data/``:
that directory is workspace state, is git-ignored, and does not exist in
a fresh clone - a test that depended on it would fail exactly where it
could not investigate.

The store lives under the test's own temporary directory, and the API
process is started with that directory as its working directory, so
nothing this file writes can reach the workspace store.
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harsh_quant_os.contracts.datasets import (
    DatasetBarsResponse,
    DatasetDetailResponse,
    DatasetListResponse,
)
from harsh_quant_os.contracts.provenance import DataQualityStatus, Timeframe
from harsh_quant_os.data import Bar, StoredDataset, store_batch, validate_bars
from harsh_quant_os.data.manifest import register_dataset

from ._http import running_api

SOURCE = "https://api.kraken.com/0/public"
DATASET_NAME = "kraken.xbtusd.1h"
SLASHED_NAME = "group/name"

#: The first three bars the recorded ingest wrote, values unchanged. Hard
#: coded so the suite proves the round trip without depending on the
#: store that happens to exist in this workspace.
_RECORDED_BARS = (
    Bar(
        symbol="XBTUSD",
        timeframe=Timeframe.H1,
        timestamp=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
        open=Decimal("78563.0"),
        high=Decimal("78854.2"),
        low=Decimal("78562.9"),
        close=Decimal("78613.7"),
        volume=Decimal("30.04552452"),
    ),
    Bar(
        symbol="XBTUSD",
        timeframe=Timeframe.H1,
        timestamp=datetime(2026, 9, 1, 1, 0, tzinfo=UTC),
        open=Decimal("78614.4"),
        high=Decimal("78772.6"),
        low=Decimal("78364.2"),
        close=Decimal("78382.1"),
        volume=Decimal("36.72525879"),
    ),
    Bar(
        symbol="XBTUSD",
        timeframe=Timeframe.H1,
        timestamp=datetime(2026, 9, 1, 2, 0, tzinfo=UTC),
        open=Decimal("78382.1"),
        high=Decimal("78430.0"),
        low=Decimal("78185.1"),
        close=Decimal("78425.8"),
        volume=Decimal("46.14447254"),
    ),
)


async def _seed(
    session_factory: async_sessionmaker[AsyncSession],
    store_root: Path,
    *,
    name: str,
) -> StoredDataset:
    """Write an artefact and register it, exactly as ``hqos data ingest`` does."""
    report = validate_bars(list(_RECORDED_BARS), timeframe=Timeframe.H1)
    stored = store_batch(
        store_root,
        name=name,
        source=SOURCE,
        raw_bars=list(_RECORDED_BARS),
        report=report,
    )
    await register_dataset(session_factory, stored)
    return stored


@pytest.fixture
async def seeded_store(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> AsyncIterator[StoredDataset]:
    """One registered dataset, whose artefact lives under ``tmp_path/data``."""
    stored = await _seed(session_factory, tmp_path / "data", name=DATASET_NAME)
    try:
        yield stored
    finally:
        # The artefact is test data in a temporary directory; removing it
        # keeps a rerun from inheriting a store from an earlier run.
        shutil.rmtree(tmp_path / "data", ignore_errors=True)


@pytest.mark.integration
async def test_a_dataset_and_its_bars_are_served_over_a_real_socket(
    seeded_store: StoredDataset,
    tmp_path: Path,
    test_database_url: str,
) -> None:
    """The read surface end to end: directory, provenance, bars, paging."""
    _ = seeded_store
    with running_api({"DATABASE_URL": test_database_url}, cwd=tmp_path) as base_url:
        # --- directory -------------------------------------------------
        listed = httpx2.get(f"{base_url}/api/v1/datasets", timeout=30.0)
        assert listed.status_code == 200
        directory = DatasetListResponse.model_validate(listed.json())
        names = [entry.name for entry in directory.datasets]
        # The test database is persistent and shared with the manifest's
        # own tests, so other rows may be present; what is asserted here
        # is that this seed is among them, in name order.
        assert DATASET_NAME in names
        assert names == sorted(names), "the directory is ordered by name"

        summary = next(entry for entry in directory.datasets if entry.name == DATASET_NAME)
        assert summary.version == seeded_store.version
        assert summary.storage_path == seeded_store.clean_path
        assert summary.quality_status is DataQualityStatus.VALID
        assert summary.instrument == "XBTUSD"
        assert summary.timeframe is Timeframe.H1
        assert summary.row_count == 3
        assert summary.source == SOURCE
        assert summary.acquired_at is not None

        # --- provenance ------------------------------------------------
        detail = httpx2.get(f"{base_url}/api/v1/datasets/{DATASET_NAME}", timeout=30.0)
        assert detail.status_code == 200
        history = DatasetDetailResponse.model_validate(detail.json())
        # The test database persists between runs and provenance is
        # append-only, so the history grows; what must hold is that the
        # newest record describes the artefact this run registered, and
        # that the order is newest first.
        assert history.provenance, "a registered dataset has at least one acquisition"
        assert history.provenance[0].acquired_at >= history.provenance[-1].acquired_at
        record = history.provenance[0]
        assert record.source == SOURCE
        assert record.checksum_sha256 == seeded_store.raw_sha256
        assert record.row_count == 3
        # The verdict *and* what was not checked travel together: an
        # acquisition that only recorded its conclusion would read better
        # than the data deserves.
        assert record.notes is not None
        assert record.notes.startswith(
            "schema, ordering, duplicates, gaps and outliers all checked"
        )
        assert "not checked: outliers were not judged" in record.notes

        # --- bars, page one --------------------------------------------
        first_page = httpx2.get(
            f"{base_url}/api/v1/datasets/{DATASET_NAME}/bars",
            params={"limit": 2},
            timeout=30.0,
        )
        assert first_page.status_code == 200
        page_one = DatasetBarsResponse.model_validate(first_page.json())
        assert page_one.version == seeded_store.version, "the page names its artefact"
        assert page_one.timeframe is Timeframe.H1
        assert page_one.quality_status is DataQualityStatus.VALID
        assert page_one.source == SOURCE
        assert page_one.returned == 2
        assert page_one.has_more is True
        assert page_one.next_cursor is not None

        # Exact digits: a price read from the artefact must arrive as the
        # string that was stored, never as a float's approximation.
        assert page_one.bars[0].timestamp == datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
        assert page_one.bars[0].open == Decimal("78563.0")
        assert page_one.bars[0].volume == Decimal("30.04552452")

        # --- bars, page two, continued by cursor ------------------------
        second_page = httpx2.get(
            f"{base_url}/api/v1/datasets/{DATASET_NAME}/bars",
            params={"limit": 2, "cursor": page_one.next_cursor},
            timeout=30.0,
        )
        assert second_page.status_code == 200
        page_two = DatasetBarsResponse.model_validate(second_page.json())
        assert page_two.returned == 1
        assert page_two.has_more is False
        assert page_two.next_cursor is None
        assert page_two.bars[0].timestamp == datetime(2026, 9, 1, 2, 0, tzinfo=UTC)
        assert page_two.bars[0].timestamp > page_one.bars[-1].timestamp, "no overlap"

        # --- an empty window is empty, not an error ---------------------
        beyond = httpx2.get(
            f"{base_url}/api/v1/datasets/{DATASET_NAME}/bars",
            params={"start": "2026-09-02T00:00:00+00:00"},
            timeout=30.0,
        )
        assert beyond.status_code == 200
        nothing = DatasetBarsResponse.model_validate(beyond.json())
        assert nothing.bars == []
        assert nothing.returned == 0
        assert nothing.has_more is False
        assert nothing.next_cursor is None


@pytest.mark.integration
async def test_dataset_failures_are_answered_honestly_over_a_real_socket(
    seeded_store: StoredDataset,
    tmp_path: Path,
    test_database_url: str,
) -> None:
    """The refusals, each with the status that says what actually happened."""
    with running_api({"DATABASE_URL": test_database_url}, cwd=tmp_path) as base_url:
        # A name the manifest does not carry: 404, not an empty page.
        unknown = httpx2.get(f"{base_url}/api/v1/datasets/no.such.dataset", timeout=30.0)
        assert unknown.status_code == 404
        assert unknown.headers["content-type"].startswith("application/problem+json")
        assert unknown.json()["title"] == "Not Found"
        assert "no.such.dataset" in unknown.json()["detail"]

        # The same for bars: an unknown dataset is not "no bars today".
        unknown_bars = httpx2.get(f"{base_url}/api/v1/datasets/no.such.dataset/bars", timeout=30.0)
        assert unknown_bars.status_code == 404

        # Request shape is judged before the database is touched.
        naive = httpx2.get(
            f"{base_url}/api/v1/datasets/{DATASET_NAME}/bars",
            params={"start": "2026-09-01T00:00:00"},
            timeout=30.0,
        )
        assert naive.status_code == 422
        assert "no UTC offset" in naive.json()["detail"]

        inverted = httpx2.get(
            f"{base_url}/api/v1/datasets/{DATASET_NAME}/bars",
            params={"start": "2026-09-02T00:00:00+00:00", "end": "2026-09-01T00:00:00+00:00"},
            timeout=30.0,
        )
        assert inverted.status_code == 422
        assert "inverted window" in inverted.json()["detail"]

        # Research reads are versioned only: probes have no dataset to show.
        unversioned = httpx2.get(f"{base_url}/datasets", timeout=30.0)
        assert unversioned.status_code == 404

        # A manifest row whose artefact has been removed says so. `data/` is
        # workspace state, so this is a state the platform must handle
        # rather than one it may assume away.
        artefact = tmp_path / "data" / Path(seeded_store.clean_path)
        assert artefact.is_file()
        artefact.unlink()
        gone = httpx2.get(
            f"{base_url}/api/v1/datasets/{DATASET_NAME}/bars",
            timeout=30.0,
        )
        assert gone.status_code == 409
        assert gone.headers["content-type"].startswith("application/problem+json")
        assert gone.json()["title"] == "Conflict"
        assert "could not be read" in gone.json()["detail"]

        # The directory still lists it - the row is intact, only the file
        # is gone - and it does not claim a series it cannot serve.
        still_listed = httpx2.get(f"{base_url}/api/v1/datasets", timeout=30.0)
        assert still_listed.status_code == 200
        assert DatasetListResponse.model_validate(still_listed.json()).datasets


@pytest.mark.integration
async def test_a_dataset_name_containing_a_separator_stays_reachable(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    test_database_url: str,
) -> None:
    """A name with a separator round-trips both ways the client can write it.

    The routes take a ``{name:path}`` capture precisely so a dataset named
    ``group/name`` is not silently unreachable, and the browser's path
    builder percent-encodes it. Both spellings are checked here, because
    an unreachable dataset would otherwise look exactly like an absent one.
    """
    stored = await _seed(session_factory, tmp_path / "data", name=SLASHED_NAME)
    try:
        with running_api({"DATABASE_URL": test_database_url}, cwd=tmp_path) as base_url:
            raw = httpx2.get(f"{base_url}/api/v1/datasets/{SLASHED_NAME}", timeout=30.0)
            assert raw.status_code == 200
            assert DatasetDetailResponse.model_validate(raw.json()).dataset.version == (
                stored.version
            )

            encoded = httpx2.get(
                f"{base_url}/api/v1/datasets/{quote(SLASHED_NAME, safe='')}",
                timeout=30.0,
            )
            assert encoded.status_code == 200, "the percent-encoded spelling must resolve too"
            assert DatasetDetailResponse.model_validate(encoded.json()).dataset.name == SLASHED_NAME
    finally:
        shutil.rmtree(tmp_path / "data", ignore_errors=True)
