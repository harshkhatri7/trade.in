"""Read-only dataset payloads: what the terminal is allowed to show.

The rule this module exists to enforce is the frontend's: *every research
figure on screen must be traceable* — dataset version, timeframe, quality
status. So every payload that carries numbers also carries the identity of
the artefact those numbers were read from, and nothing here computes,
averages, resamples or estimates anything. The API reports what is stored
and where it came from; interpretation belongs to whoever is researching.

Three shapes:

* :class:`DatasetSummary` / :class:`DatasetListResponse` — the directory.
* :class:`DatasetDetailResponse` — one dataset with its append-only
  acquisition history.
* :class:`DatasetBarsResponse` — a page of OHLCV, tagged with the version
  it was read from.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harsh_quant_os.contracts.provenance import DataQualityStatus, Timeframe


class DatasetSummary(BaseModel):
    """One dataset: identity, verdict, and where its data came from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    instrument: str | None
    timeframe: Timeframe | None
    quality_status: DataQualityStatus
    #: SHA-256 of the clean artefact, or ``None`` when nothing is stored.
    #: A ``datasets`` row can exist before its artefact does, and reporting
    #: a version it does not have would be the first untraceable number on
    #: the screen. The key is always present; only the value is nullable,
    #: which is what the TypeScript mirror declares too.
    version: str | None
    storage_path: str | None
    #: From the most recent acquisition record, never recomputed from the
    #: file: provenance describes what arrived, not what the file looks
    #: like now.
    source: str | None
    acquired_at: datetime | None
    row_count: int | None
    updated_at: datetime


class DatasetProvenanceEntry(BaseModel):
    """One acquisition. Append-only: corrections are another entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    acquired_at: datetime
    source: str
    #: ``None`` means *not checked*, never *matched*.
    checksum_sha256: str | None
    #: ``None`` means *not counted*, never *zero*.
    row_count: int | None
    notes: str | None


class DatasetListResponse(BaseModel):
    """Every dataset in the manifest, ordered by name."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    datasets: list[DatasetSummary]


class DatasetDetailResponse(BaseModel):
    """One dataset plus its acquisition history, newest first."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: DatasetSummary
    provenance: list[DatasetProvenanceEntry]


class BarPoint(BaseModel):
    """One OHLCV point, quoted exactly as stored — never resampled here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None


class DatasetBarsResponse(BaseModel):
    """A page of bars, tagged with the version they were read from.

    The tag is the point: a chart built from this payload can show, next
    to any figure it draws, the artefact that figure came from.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: str
    instrument: str | None
    timeframe: Timeframe
    quality_status: DataQualityStatus
    source: str | None
    bars: list[BarPoint]
    #: Cursor pagination, per the API conventions: ``next_cursor`` is the
    #: timestamp to pass back to continue, and ``has_more`` says whether
    #: there is anything after it. ``None`` when the page is the end.
    returned: int = Field(ge=0)
    has_more: bool
    next_cursor: str | None

    @model_validator(mode="after")
    def _page_is_coherent(self) -> Self:
        """Two rules the browser relies on, checked before anything is served.

        ``returned`` must describe the array it sits beside, and a page
        that claims there is more must hand back the cursor that reaches
        it. Either being false would turn the next request into a guess,
        so both are refused here rather than noticed by a caller.
        """
        if self.returned != len(self.bars):
            raise ValueError(f"returned says {self.returned} but {len(self.bars)} bars were sent")
        if self.has_more and self.next_cursor is None:
            raise ValueError("has_more is true but no next_cursor was given")
        return self


__all__ = [
    "BarPoint",
    "DatasetBarsResponse",
    "DatasetDetailResponse",
    "DatasetListResponse",
    "DatasetProvenanceEntry",
    "DatasetSummary",
]
