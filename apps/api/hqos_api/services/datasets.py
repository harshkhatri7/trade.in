"""Reading stored datasets for the terminal: manifest and artefact, read-only.

The terminal's claim is traceability — a figure on screen can name the
dataset version it came from — so these loaders do exactly three things:

1. read the manifest row and its acquisition history;
2. read the artefact back through the store's own reader, so a bar the
   API serves is the byte that was validated, not a second
   interpretation of it;
3. slice the requested window into a page.

Nothing is resampled, averaged, interpolated or carried forward. A window
with no bars comes back empty rather than with the nearest thing, and a
dataset whose artefact has gone missing says so instead of quietly
returning fewer bars than the manifest claims.

Failures are raised as :class:`DatasetNotFound` or
:class:`DatasetNotStored`; turning those into HTTP statuses belongs to the
router, which is where request shape and status codes live. Nothing here
knows what HTTP is.
"""

from __future__ import annotations

import asyncio
import csv
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harsh_quant_os.contracts.datasets import (
    BarPoint,
    DatasetBarsResponse,
    DatasetDetailResponse,
    DatasetListResponse,
    DatasetProvenanceEntry,
    DatasetSummary,
)
from harsh_quant_os.contracts.provenance import DataQualityStatus, Timeframe
from harsh_quant_os.data import Bar, artifact_path, read_bars
from harsh_quant_os.data.manifest import dataset_by_name, list_datasets, provenance_history
from harsh_quant_os.data.store import StorePathEscapes
from harsh_quant_os.db.models import Dataset, DatasetProvenance

#: Bars returned when the caller does not ask for a number. Small enough
#: that an accidental request stays cheap, large enough that a screenful
#: of a 1h chart arrives in one round trip.
DEFAULT_BARS_LIMIT = 500
#: Upper bound, so one request cannot ask for a decade of ticks and turn
#: a read-only endpoint into a memory event.
MAX_BARS_LIMIT = 5000


class DatasetReadError(Exception):
    """A registered dataset cannot be served as it was asked for."""


class DatasetNotFound(DatasetReadError):
    """No manifest row carries that name. Maps to 404."""


class DatasetNotStored(DatasetReadError):
    """The row exists, but there is no readable artefact behind it.

    Possible because ``data/`` is workspace state rather than repository
    state: a manifest row outlives a deletion of the files it points at.
    Maps to 409 — the dataset is known, this request conflicts with the
    state it is actually in.
    """


def build_summary(dataset: Dataset, latest: DatasetProvenance | None) -> DatasetSummary:
    """Project one manifest row, and its most recent acquisition, onto the contract.

    ``latest`` is ``None`` only for a dataset that has never been
    recorded as acquired; its provenance fields stay ``None`` rather than
    being filled with zeros, because "not recorded" and "zero" are
    different claims.
    """
    return DatasetSummary(
        name=dataset.name,
        instrument=dataset.instrument,
        timeframe=Timeframe(dataset.timeframe) if dataset.timeframe else None,
        quality_status=DataQualityStatus(dataset.quality_status),
        version=dataset.version,
        storage_path=dataset.storage_path,
        source=latest.source if latest is not None else None,
        acquired_at=latest.acquired_at if latest is not None else None,
        row_count=latest.row_count if latest is not None else None,
        updated_at=dataset.updated_at,
    )


def build_provenance_entry(row: DatasetProvenance) -> DatasetProvenanceEntry:
    """Project one acquisition record onto the contract."""
    return DatasetProvenanceEntry(
        acquired_at=row.acquired_at,
        source=row.source,
        checksum_sha256=row.checksum_sha256,
        row_count=row.row_count,
        notes=row.notes,
    )


def build_bar_point(bar: Bar) -> BarPoint:
    """Project one stored bar onto the contract, unchanged."""
    return BarPoint(
        timestamp=bar.timestamp,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
    )


async def load_datasets(session_factory: async_sessionmaker[AsyncSession]) -> DatasetListResponse:
    """Every dataset in the manifest, each with its most recent acquisition.

    Two queries, not one per row: the directory is a list, and a list
    that costs N+1 round trips punishes having more data.
    """
    rows = await list_datasets(session_factory)
    history = await provenance_history(session_factory, [row.id for row in rows])
    return DatasetListResponse(
        datasets=[
            build_summary(row, history[row.id][0] if history[row.id] else None) for row in rows
        ]
    )


async def load_dataset_detail(
    session_factory: async_sessionmaker[AsyncSession],
    name: str,
) -> DatasetDetailResponse:
    """One dataset with its full acquisition history, newest first.

    Raises :class:`DatasetNotFound` when the manifest has no such row.
    """
    dataset = await dataset_by_name(session_factory, name)
    if dataset is None:
        raise DatasetNotFound(f"no dataset is registered under the name {name!r}") from None
    history = await provenance_history(session_factory, [dataset.id])
    records = history[dataset.id]
    return DatasetDetailResponse(
        dataset=build_summary(dataset, records[0] if records else None),
        provenance=[build_provenance_entry(row) for row in records],
    )


def _window(
    bars: list[Bar],
    *,
    start: datetime | None,
    end: datetime | None,
    cursor: datetime | None,
) -> list[Bar]:
    selected = bars
    if start is not None:
        selected = [bar for bar in selected if bar.timestamp >= start]
    if end is not None:
        selected = [bar for bar in selected if bar.timestamp <= end]
    if cursor is not None:
        # Exclusive: the cursor is the timestamp of the last bar the
        # caller already has, so returning it again would duplicate it.
        selected = [bar for bar in selected if bar.timestamp > cursor]
    return selected


async def load_bars(
    session_factory: async_sessionmaker[AsyncSession],
    store_root: Path,
    *,
    name: str,
    start: datetime | None = None,
    end: datetime | None = None,
    cursor: datetime | None = None,
    limit: int = DEFAULT_BARS_LIMIT,
) -> DatasetBarsResponse:
    """One page of a stored dataset's bars, tagged with its version.

    Raises :class:`DatasetNotFound` when the name is not registered, and
    :class:`DatasetNotStored` when the row exists but cannot be read —
    no artefact, a timeframe missing from the manifest, a path that
    escapes the store, or a file that is not there any more.
    """
    dataset = await dataset_by_name(session_factory, name)
    if dataset is None:
        raise DatasetNotFound(f"no dataset is registered under the name {name!r}") from None
    if not dataset.version or not dataset.storage_path:
        raise DatasetNotStored(f"the manifest row for {name!r} has no stored artefact")
    if not dataset.timeframe:
        # The response has to label its bars with a timeframe, and
        # guessing one from the spacing of timestamps would be inventing
        # metadata the manifest does not have.
        raise DatasetNotStored(f"the manifest row for {name!r} carries no timeframe")

    try:
        path = artifact_path(store_root, dataset.storage_path)
    except StorePathEscapes as exc:
        raise DatasetNotStored(f"the manifest row for {name!r} points outside the store") from exc

    try:
        # File I/O off the event loop: the endpoint is async and shares
        # the loop with every other request.
        bars = await asyncio.to_thread(read_bars, path)
    except (OSError, ValueError, csv.Error) as exc:
        raise DatasetNotStored(
            f"the stored artefact for {name!r} could not be read; "
            f"the manifest lists it at {dataset.storage_path}"
        ) from exc

    history = await provenance_history(session_factory, [dataset.id])
    records = history[dataset.id]
    selected = _window(bars, start=start, end=end, cursor=cursor)
    page = selected[:limit]
    has_more = len(selected) > limit
    return DatasetBarsResponse(
        name=dataset.name,
        version=dataset.version,
        instrument=dataset.instrument,
        timeframe=Timeframe(dataset.timeframe),
        quality_status=DataQualityStatus(dataset.quality_status),
        source=records[0].source if records else None,
        bars=[build_bar_point(bar) for bar in page],
        returned=len(page),
        has_more=has_more,
        next_cursor=page[-1].timestamp.isoformat() if has_more and page else None,
    )


__all__ = [
    "DEFAULT_BARS_LIMIT",
    "MAX_BARS_LIMIT",
    "DatasetNotFound",
    "DatasetNotStored",
    "DatasetReadError",
    "build_bar_point",
    "build_provenance_entry",
    "build_summary",
    "load_bars",
    "load_dataset_detail",
    "load_datasets",
]
