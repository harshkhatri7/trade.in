"""The local dataset store, including the promises that make it a *store*.

What is under test is not just that files appear. It is that:

- a value read back is the value written, digit for digit;
- the same batch always lands in the same place, and a different batch
  never lands in an existing one, so ``raw/`` can be called immutable;
- what validation refused cannot be stored as a dataset by any route
  except quarantine, and quarantine does not touch ``clean/``;
- a dataset name cannot be turned into a path outside the store.

Everything runs against a temporary directory. No network, no database,
and nothing written outside ``tmp_path``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from harsh_quant_os.contracts.provenance import DataQualityStatus, Timeframe
from harsh_quant_os.data import (
    Bar,
    StoreRefused,
    ValidationReport,
    quarantine_batch,
    read_bars,
    store_batch,
    validate_bars,
)

ORIGIN = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)


def _bar(at: datetime, *, volume: Decimal | None = Decimal("1000")) -> Bar:
    return Bar(
        symbol="TEST.NEUTRAL",
        timeframe=Timeframe.M1,
        timestamp=at,
        open=Decimal("100.00"),
        high=Decimal("101.25"),
        low=Decimal("99.75"),
        close=Decimal("100.50"),
        volume=volume,
    )


def _minutes(count: int, *, skip_volume_at: int | None = None) -> list[Bar]:
    return [
        _bar(
            ORIGIN + timedelta(minutes=index),
            volume=None if index == skip_volume_at else Decimal("1000"),
        )
        for index in range(count)
    ]


def test_a_stored_batch_reads_back_exactly_as_it_went_in(tmp_path: Path) -> None:
    """A price that changes on the way in was not stored exactly."""
    bars = _minutes(10)
    report = validate_bars(bars, timeframe=Timeframe.M1)

    stored = store_batch(tmp_path, name="test.minute", source="unit", raw_bars=bars, report=report)
    restored = read_bars(tmp_path / stored.clean_path)

    assert restored == bars
    assert restored[0].close == Decimal("100.50")
    assert restored[0].timestamp.tzinfo is not None


def test_a_bar_with_no_volume_reads_back_as_none_rather_than_zero(tmp_path: Path) -> None:
    bars = _minutes(6, skip_volume_at=3)
    report = validate_bars(bars, timeframe=Timeframe.M1)

    stored = store_batch(tmp_path, name="test.minute", source="unit", raw_bars=bars, report=report)
    restored = read_bars(tmp_path / stored.clean_path)

    assert restored[3].volume is None
    assert restored[3].volume != 0


def test_the_same_bars_always_land_on_the_same_path(tmp_path: Path) -> None:
    """Phase 3 requires a re-ingest to produce an identical version."""
    bars = _minutes(12)
    report = validate_bars(bars, timeframe=Timeframe.M1)

    first = store_batch(tmp_path, name="test.minute", source="unit", raw_bars=bars, report=report)
    second = store_batch(tmp_path, name="test.minute", source="unit", raw_bars=bars, report=report)

    assert first.version == second.version
    assert first.clean_path == second.clean_path
    assert first.raw_path == second.raw_path


def test_different_bars_land_on_a_different_path(tmp_path: Path) -> None:
    first_report = validate_bars(_minutes(12), timeframe=Timeframe.M1)
    second_report = validate_bars(_minutes(13), timeframe=Timeframe.M1)

    first = store_batch(
        tmp_path, name="test.minute", source="unit", raw_bars=_minutes(12), report=first_report
    )
    second = store_batch(
        tmp_path, name="test.minute", source="unit", raw_bars=_minutes(13), report=second_report
    )

    assert first.version != second.version
    assert first.raw_path != second.raw_path, "a different payload overwrote an earlier artefact"


def test_storing_twice_writes_the_files_only_once(tmp_path: Path) -> None:
    bars = _minutes(12)
    report = validate_bars(bars, timeframe=Timeframe.M1)

    store_batch(tmp_path, name="test.minute", source="unit", raw_bars=bars, report=report)
    written = sorted(path for path in tmp_path.rglob("*") if path.is_file())
    stamps = {path: path.stat().st_mtime_ns for path in written}

    store_batch(tmp_path, name="test.minute", source="unit", raw_bars=bars, report=report)
    after = sorted(path for path in tmp_path.rglob("*") if path.is_file())

    assert after == written, "a second identical store created new files"
    assert all(path.stat().st_mtime_ns == stamps[path] for path in after), "a file was rewritten"


def test_no_partial_file_is_left_behind(tmp_path: Path) -> None:
    bars = _minutes(5)
    report = validate_bars(bars, timeframe=Timeframe.M1)

    store_batch(tmp_path, name="test.minute", source="unit", raw_bars=bars, report=report)

    assert list(tmp_path.rglob("*.partial")) == [], "a partial file survived the write"


def test_the_store_refuses_a_batch_validation_refused(tmp_path: Path) -> None:
    bars = _minutes(6)
    bars[3], bars[4] = bars[4], bars[3]
    report = validate_bars(bars, timeframe=Timeframe.M1)
    assert report.status is DataQualityStatus.INVALID

    with pytest.raises(StoreRefused) as raised:
        store_batch(tmp_path, name="test.minute", source="unit", raw_bars=bars, report=report)

    assert raised.value.report is report, "the reason for refusal was not carried out"
    assert not (tmp_path / "clean").exists(), "invalid data reached the clean store"
    assert not (tmp_path / "raw").exists(), "invalid data was written as if it had landed"


def test_quarantine_keeps_the_batch_and_the_report_that_refused_it(tmp_path: Path) -> None:
    bars = _minutes(6)
    bars[3], bars[4] = bars[4], bars[3]
    report = validate_bars(bars, timeframe=Timeframe.M1)

    record = quarantine_batch(
        tmp_path, name="test.minute", source="unit", raw_bars=bars, report=report
    )

    assert record.status is DataQualityStatus.INVALID
    assert (tmp_path / record.payload_path).is_file()
    written_report = (tmp_path / record.report_path).read_text(encoding="utf-8")
    assert "not strictly increasing" in written_report
    assert read_bars(tmp_path / record.payload_path) == bars, (
        "the refused data was not kept as sent"
    )


def test_quarantine_never_touches_the_clean_store(tmp_path: Path) -> None:
    bars = _minutes(6)
    bars[3], bars[4] = bars[4], bars[3]
    report = validate_bars(bars, timeframe=Timeframe.M1)

    quarantine_batch(tmp_path, name="test.minute", source="unit", raw_bars=bars, report=report)

    assert not (tmp_path / "clean").exists()
    assert not (tmp_path / "raw").exists()


def test_a_dataset_name_cannot_escape_the_store_root(tmp_path: Path) -> None:
    bars = _minutes(4)
    report = validate_bars(bars, timeframe=Timeframe.M1)

    stored = store_batch(
        tmp_path, name="../../etc/passwd", source="unit", raw_bars=bars, report=report
    )

    resolved = (tmp_path / stored.clean_path).resolve()
    assert resolved.is_relative_to(tmp_path.resolve())
    assert ".." not in stored.clean_path
    assert resolved.is_file()


def test_a_name_with_no_usable_characters_is_refused(tmp_path: Path) -> None:
    bars = _minutes(4)
    report = validate_bars(bars, timeframe=Timeframe.M1)

    with pytest.raises(StoreRefused, match="usable characters"):
        store_batch(tmp_path, name="///", source="unit", raw_bars=bars, report=report)


def test_a_batch_spanning_two_instruments_is_refused(tmp_path: Path) -> None:
    """A dataset is one instrument; mixing them would mislabel every row."""
    bars = _minutes(4)
    intruder = Bar(
        symbol="OTHER.NEUTRAL",
        timeframe=Timeframe.M1,
        timestamp=ORIGIN + timedelta(minutes=99),
        open=Decimal("1.00"),
        high=Decimal("1.10"),
        low=Decimal("0.90"),
        close=Decimal("1.05"),
        volume=Decimal("10"),
    )
    mixed = [*bars, intruder]
    report = validate_bars(mixed, timeframe=Timeframe.M1)

    with pytest.raises(StoreRefused, match="one instrument"):
        store_batch(tmp_path, name="test.minute", source="unit", raw_bars=mixed, report=report)

    assert not (tmp_path / "clean").exists()


def test_the_manifest_fields_describe_what_was_actually_written(tmp_path: Path) -> None:
    bars = _minutes(12)
    bars.insert(5, _bar(ORIGIN + timedelta(minutes=4)))
    report = validate_bars(bars, timeframe=Timeframe.M1)
    assert report.duplicates_removed == 1

    stored = store_batch(tmp_path, name="test.minute", source="unit", raw_bars=bars, report=report)

    assert stored.row_count == len(report.accepted_bars) == 12
    assert stored.received == 13
    assert stored.duplicates_removed == 1
    assert stored.instrument == "TEST.NEUTRAL"
    assert stored.timeframe is Timeframe.M1
    assert stored.quality_status is report.status
    assert stored.gaps == len(report.gaps)
    assert stored.outliers == len(report.outliers)
    assert len(stored.version) == 64


def test_raw_and_clean_are_separate_artefacts_with_separate_hashes(tmp_path: Path) -> None:
    bars = _minutes(12)
    bars.insert(5, _bar(ORIGIN + timedelta(minutes=4)))
    report = validate_bars(bars, timeframe=Timeframe.M1)

    stored = store_batch(tmp_path, name="test.minute", source="unit", raw_bars=bars, report=report)

    assert (tmp_path / stored.raw_path).is_file()
    assert (tmp_path / stored.clean_path).is_file()
    assert stored.raw_sha256 != stored.version, "raw and clean were assumed identical"
    assert len(read_bars(tmp_path / stored.raw_path)) == 13, "raw must keep every row received"
    assert len(read_bars(tmp_path / stored.clean_path)) == 12


def test_the_store_is_rooted_where_it_was_told_to_be(tmp_path: Path) -> None:
    """A test that writes outside its sandbox proves nothing about safety."""
    root = tmp_path / "elsewhere"
    bars = _minutes(4)
    report: ValidationReport = validate_bars(bars, timeframe=Timeframe.M1)

    store_batch(root, name="test.minute", source="unit", raw_bars=bars, report=report)

    assert (root / "clean").is_dir()
    assert not (tmp_path / "clean").exists()
