"""Writing validated batches to the local dataset store.

The layout is data-platform.md section 4, and each of the three
subdirectories has a different promise:

- ``raw/`` — what arrived, byte-faithful to what the provider sent, never
  edited in place.
- ``clean/`` — the bars that survived validation, in canonical form.
- ``quarantine/`` — batches validation refused, kept with their report so
  the refusal can be examined. Never merged into ``clean/``.

Three rules hold throughout, and each one costs a convenience:

1. **Directories are content-addressed.** The path is derived from the
   SHA-256 of the artefact, so two runs of the same input land on the same
   path and a different input cannot land on an existing one. Nothing here
   can overwrite an earlier artefact, which is what "immutable" has to
   mean for ``raw/`` to be worth calling immutable. It also makes a re-ingest
   idempotent: the work is already done, and the existing file is reused
   rather than rewritten.

2. **Invalid batches are never written as datasets.** Validation's verdict
   is authoritative; a caller cannot store what validation refused by
   simply not asking. ``store_batch`` raises :class:`StoreRefused` with the
   report attached, and :func:`quarantine_batch` is the only path that
   writes such a batch anywhere.

3. **Writes are atomic.** Content goes to a temporary file and is moved
   into place, so a process that dies mid-write leaves no half-file that a
   later reader would take for a complete one.

The manifest — the mapping from a logical dataset name to its physical
files and version — lives in PostgreSQL (``datasets`` plus the append-only
``dataset_provenance``); these functions return the values that manifest
needs. ``data/`` is git-ignored in full, so nothing written here can be
committed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from harsh_quant_os.contracts.provenance import DataQualityStatus, Timeframe
from harsh_quant_os.data.providers import Bar
from harsh_quant_os.data.validation import ValidationReport

__all__ = [
    "QuarantineRecord",
    "StoreRefused",
    "StoredDataset",
    "quarantine_batch",
    "read_bars",
    "store_batch",
]

_FIELDS = ("symbol", "timeframe", "timestamp", "open", "high", "low", "close", "volume")

#: Dataset names become directory names, so anything that is not a plain
#: filename character is replaced rather than trusted. ``../../x`` must not
#: resolve outside the store, and testing that is cheaper than reasoning
#: about it.
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class StoreRefused(Exception):
    """The batch may not be stored as a dataset.

    Carries the report so a caller can show *why* without re-running
    validation.
    """

    def __init__(self, message: str, *, report: ValidationReport) -> None:
        super().__init__(message)
        self.report = report


class StoredDataset(BaseModel):
    """What a successful store produced. Deterministic for a given input."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    source: str
    instrument: str
    timeframe: Timeframe
    #: SHA-256 of the clean artefact. Same bars, same version; different
    #: bars, different version. This is what makes a re-ingest reproducible.
    version: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_status: DataQualityStatus
    raw_path: str = Field(description="Path relative to the store root, POSIX separators.")
    clean_path: str = Field(description="Path relative to the store root, POSIX separators.")
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_count: int = Field(ge=1)
    received: int = Field(ge=1)
    duplicates_removed: int = Field(ge=0)
    gaps: int = Field(ge=0)
    outliers: int = Field(ge=0)
    #: What validation said about this batch, carried so the manifest can
    #: record *why* the status is what it is rather than only what it is.
    reasons: tuple[str, ...]
    #: What validation could not check, carried for the same reason: a
    #: stored dataset whose caveats were dropped at the door would read
    #: better than it deserves to.
    notes: tuple[str, ...]


class QuarantineRecord(BaseModel):
    """Where a refused batch was kept, and what was refused about it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    source: str
    version: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: DataQualityStatus
    payload_path: str
    report_path: str
    received: int = Field(ge=0)
    reasons: tuple[str, ...]


def _none() -> ValidationReport:
    """A placeholder report for errors raised before validation ran.

    Only the message matters in that case, and inventing a verdict would
    be worse than carrying an empty one that no caller can mistake for a
    result: ``received`` is 0 and the status says ``unknown``.
    """
    return ValidationReport(
        status=DataQualityStatus.UNKNOWN,
        reasons=("no validation ran; this error is about the request, not the data",),
        notes=(),
        received=0,
        duplicates_removed=0,
        disagreeing_duplicates=0,
        gaps=(),
        outliers=(),
        accepted_bars=(),
    )


def _slug_for(name: str, *, report: ValidationReport) -> str:
    cleaned = _UNSAFE_NAME.sub("_", name).strip("._")
    if not cleaned:
        raise StoreRefused(f"dataset name {name!r} contains no usable characters", report=report)
    return cleaned


def _bars_to_csv(bars: Sequence[Bar]) -> bytes:
    """Canonical serialisation: one encoding, one line ending, exact values."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_FIELDS)
    for bar in bars:
        writer.writerow(
            (
                bar.symbol,
                bar.timeframe.value,
                bar.timestamp.isoformat(),
                str(bar.open),
                str(bar.high),
                str(bar.low),
                str(bar.close),
                "" if bar.volume is None else str(bar.volume),
            )
        )
    return buffer.getvalue().encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_atomic(path: Path, payload: bytes) -> None:
    """Publish a file only once it is complete."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _read_or_write(path: Path, payload: bytes) -> bool:
    """Write ``payload`` unless ``path`` already holds exactly that.

    Returns whether a write happened. Because directories are
    content-addressed, an existing file with this name already has this
    content; reusing it is what makes a re-ingest idempotent.
    """
    if path.exists():
        if path.read_bytes() != payload:
            raise StoreRefused(
                f"{path} exists with different content than the artefact being stored",
                report=_none(),
            )
        return False
    _write_atomic(path, payload)
    return True


def store_batch(
    root: Path,
    *,
    name: str,
    source: str,
    raw_bars: Sequence[Bar],
    report: ValidationReport,
) -> StoredDataset:
    """Write ``raw_bars`` and the validated bars under ``root``.

    Raises :class:`StoreRefused` when validation refused the batch. The
    refusal is not a caller's to override: invalid data is quarantined, and
    this function has no switch that changes that.
    """
    if report.status is DataQualityStatus.INVALID:
        raise StoreRefused(
            f"validation returned {report.status.value}: {report.reasons[0] if report.reasons else 'no reason recorded'}",
            report=report,
        )

    if not raw_bars:
        raise StoreRefused("there is no raw payload to store", report=report)
    if not report.accepted_bars:
        raise StoreRefused(
            "no bars survived validation, so there is nothing clean to store", report=report
        )

    symbols = {bar.symbol for bar in raw_bars}
    if len(symbols) != 1:
        raise StoreRefused(
            f"a dataset is one instrument; this batch carries {len(symbols)}: "
            + ", ".join(sorted(symbols)),
            report=report,
        )

    clean_payload = _bars_to_csv(report.accepted_bars)
    raw_payload = _bars_to_csv(raw_bars)
    version = _sha256(clean_payload)
    slug = _slug_for(name, report=report)
    instrument = next(iter(symbols))

    raw_path = root / "raw" / slug / version / "raw.csv"
    clean_path = root / "clean" / slug / version / "bars.csv"

    _read_or_write(raw_path, raw_payload)
    _read_or_write(clean_path, clean_payload)

    return StoredDataset(
        name=name,
        source=source,
        instrument=instrument,
        timeframe=report.accepted_bars[0].timeframe,
        version=version,
        quality_status=report.status,
        raw_path=raw_path.relative_to(root).as_posix(),
        clean_path=clean_path.relative_to(root).as_posix(),
        raw_sha256=_sha256(raw_payload),
        row_count=len(report.accepted_bars),
        received=report.received,
        duplicates_removed=report.duplicates_removed,
        gaps=len(report.gaps),
        outliers=len(report.outliers),
        reasons=report.reasons,
        notes=report.notes,
    )


def quarantine_batch(
    root: Path,
    *,
    name: str,
    source: str,
    raw_bars: Sequence[Bar],
    report: ValidationReport,
) -> QuarantineRecord:
    """Keep a refused batch with the report that refused it.

    The data is not thrown away — a discarded batch is an unanswerable
    question later — and it is not written to ``clean/`` either, so nothing
    downstream can pick it up by accident.
    """
    payload = _bars_to_csv(raw_bars)
    version = _sha256(payload)
    slug = _slug_for(name, report=report)

    payload_path = root / "quarantine" / slug / version / "payload.csv"
    report_path = root / "quarantine" / slug / version / "report.json"

    _read_or_write(payload_path, payload)
    _read_or_write(report_path, report.model_dump_json(indent=2).encode("utf-8"))

    return QuarantineRecord(
        name=name,
        source=source,
        version=version,
        status=report.status,
        payload_path=payload_path.relative_to(root).as_posix(),
        report_path=report_path.relative_to(root).as_posix(),
        received=report.received,
        reasons=report.reasons,
    )


def read_bars(path: Path) -> list[Bar]:
    """Read an artefact written by this module back into bars.

    Round-tripping is not incidental: a value that cannot be read back
    unchanged was not stored exactly, and a store that quietly loses
    precision on the way in would defeat the reason prices are ``Decimal``.
    """
    bars: list[Bar] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            record: dict[str, object] = dict(row)
            if record.get("volume") in (None, ""):
                record["volume"] = None
            bars.append(Bar.model_validate(record))
    return bars
