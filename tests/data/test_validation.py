"""Validation, asserted against the promises data-platform.md section 3 makes.

Each test pins one of those promises, and two of them pin the *absence* of
a behaviour: nothing here reorders, fills, clamps or otherwise repairs a
batch. A validator that quietly fixed data would be worse than no
validator, because the fixing would not be in the report.

Nothing here touches the network. The bars are built locally from a
deterministic sequence, so a failing assertion means the rule moved, not
that a provider changed its mind.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from harsh_quant_os.contracts.provenance import DataQualityStatus, Timeframe
from harsh_quant_os.data import (
    Bar,
    InvalidProviderPayload,
    ValidationReport,
    parse_rows,
    validate_bars,
)

ORIGIN = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)


def _bar(at: datetime, *, range_size: Decimal = Decimal("1.00")) -> Bar:
    """One OHLCV bar whose high-low span is exactly ``range_size``."""
    return Bar(
        symbol="TEST.NEUTRAL",
        timeframe=Timeframe.M1,
        timestamp=at,
        open=Decimal("100.00"),
        high=Decimal("100.00") + range_size,
        low=Decimal("100.00"),
        close=Decimal("100.00") + (range_size / 2),
        volume=Decimal("1000"),
    )


def _minute_series(count: int, *, ranges: dict[int, Decimal] | None = None) -> list[Bar]:
    """``count`` consecutive 1-minute bars, optionally varying each range."""
    selected = ranges or {}
    return [
        _bar(ORIGIN + timedelta(minutes=index), range_size=selected.get(index, Decimal("1.00")))
        for index in range(count)
    ]


def _daily_series(days: int) -> list[Bar]:
    """``days`` consecutive 1-day bars, raw-spaced (weekends included)."""
    return [
        Bar(
            symbol="TEST.NEUTRAL",
            timeframe=Timeframe.D1,
            timestamp=ORIGIN + timedelta(days=index),
            open=Decimal("100.00"),
            high=Decimal("101.00"),
            low=Decimal("99.00"),
            close=Decimal("100.50"),
            volume=Decimal("1000"),
        )
        for index in range(days)
    ]


def test_an_empty_batch_is_invalid_because_there_is_nothing_to_store() -> None:
    report = validate_bars([], timeframe=Timeframe.M1)

    assert report.status is DataQualityStatus.INVALID
    assert report.is_storable is False
    assert any("no bars" in reason for reason in report.reasons)


def test_a_clean_series_validates_and_returns_its_bars_unchanged() -> None:
    bars = _minute_series(30)

    report = validate_bars(bars, timeframe=Timeframe.M1)

    assert report.status is DataQualityStatus.VALID
    assert report.is_storable is True
    assert report.received == 30
    assert report.accepted_bars == tuple(bars), "validation altered the batch"
    assert report.duplicates_removed == 0
    assert report.gaps == ()
    assert report.outliers == ()


def test_the_same_input_always_produces_the_same_report() -> None:
    """Phase 3 requires a re-ingest to yield an identical version."""
    bars = _minute_series(40, ranges={7: Decimal("40.00")})

    first = validate_bars(bars, timeframe=Timeframe.M1)
    second = validate_bars(bars, timeframe=Timeframe.M1)

    assert first.model_dump() == second.model_dump()


def test_duplicate_timestamps_are_counted_rather_than_absorbed() -> None:
    bars = _minute_series(10)
    bars.insert(5, _bar(ORIGIN + timedelta(minutes=4), range_size=Decimal("1.00")))

    report = validate_bars(bars, timeframe=Timeframe.M1)

    assert report.received == 11
    assert report.duplicates_removed == 1
    assert len(report.accepted_bars) == 10
    assert any("duplicate" in reason for reason in report.reasons)
    assert report.status is DataQualityStatus.VALID, "a repeat of identical values is not suspect"


def test_a_duplicate_that_disagrees_is_reported_and_marks_the_batch_suspect() -> None:
    """Two values for one instant is a provider inconsistency, not noise."""
    bars = _minute_series(10)
    conflicting = Bar(
        symbol="TEST.NEUTRAL",
        timeframe=Timeframe.M1,
        timestamp=ORIGIN + timedelta(minutes=4),
        open=Decimal("100.00"),
        high=Decimal("109.00"),
        low=Decimal("99.00"),
        close=Decimal("104.00"),
        volume=Decimal("1000"),
    )
    bars.insert(5, conflicting)

    report = validate_bars(bars, timeframe=Timeframe.M1)

    assert report.duplicates_removed == 1
    assert report.disagreeing_duplicates == 1
    assert report.status is DataQualityStatus.SUSPECT
    assert report.is_storable is True, "suspect data is stored and flagged, not discarded"
    assert any("disagreed" in reason for reason in report.reasons)


def test_out_of_order_timestamps_reject_the_batch_and_are_not_sorted() -> None:
    """Reordering would be repairing the batch behind the caller's back."""
    bars = _minute_series(6)
    bars[3], bars[4] = bars[4], bars[3]
    original_order = [bar.timestamp for bar in bars]

    report = validate_bars(bars, timeframe=Timeframe.M1)

    assert report.status is DataQualityStatus.INVALID
    assert report.is_storable is False
    assert report.accepted_bars == ()
    assert any("not strictly increasing" in reason for reason in report.reasons)
    assert [bar.timestamp for bar in bars] == original_order, "the input was reordered"


def test_a_gap_is_recorded_with_how_many_bars_were_missing() -> None:
    bars = _minute_series(5) + [_bar(ORIGIN + timedelta(minutes=10 + index)) for index in range(5)]

    report = validate_bars(bars, timeframe=Timeframe.M1)

    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.after == ORIGIN + timedelta(minutes=4)
    assert gap.before == ORIGIN + timedelta(minutes=10)
    assert gap.expected_missing == 5
    assert report.status is DataQualityStatus.VALID, "a gap is metadata, not a verdict"


def test_daily_gaps_say_that_the_session_calendar_was_not_consulted() -> None:
    """Weekends would otherwise be reported as if trading days were missing."""
    bars = [
        Bar(
            symbol="TEST.NEUTRAL",
            timeframe=Timeframe.D1,
            timestamp=ORIGIN + timedelta(days=index),
            open=Decimal("100.00"),
            high=Decimal("101.00"),
            low=Decimal("99.00"),
            close=Decimal("100.50"),
            volume=Decimal("1000"),
        )
        for index in (0, 1, 2, 10, 11, 12)
    ]

    report = validate_bars(bars, timeframe=Timeframe.D1)

    assert len(report.gaps) == 1
    assert report.gaps[0].expected_missing == 7
    assert any("session calendar" in note for note in report.notes)


def test_timeframes_without_a_fixed_interval_report_that_gaps_were_not_computed() -> None:
    bars = [
        Bar(
            symbol="TEST.NEUTRAL",
            timeframe=Timeframe.MN1,
            timestamp=datetime(2026, 1 + index, 1, tzinfo=UTC),
            open=Decimal("100.00"),
            high=Decimal("101.00"),
            low=Decimal("99.00"),
            close=Decimal("100.50"),
            volume=None,
        )
        for index in range(6)
    ]

    report = validate_bars(bars, timeframe=Timeframe.MN1)

    assert report.gaps == ()
    assert any("no fixed interval" in note for note in report.notes)


def test_a_series_too_short_to_judge_outliers_says_so_instead_of_guessing() -> None:
    report = validate_bars(_minute_series(5), timeframe=Timeframe.M1)

    assert report.outliers == ()
    assert report.status is DataQualityStatus.VALID
    assert any("outliers were not judged" in note for note in report.notes)


def test_every_bar_having_the_same_range_leaves_the_outlier_rule_unable_to_measure() -> None:
    """Zero spread is not evidence of no outliers; it is no variation to
    measure with, and the report must not claim otherwise."""
    report = validate_bars(_minute_series(50), timeframe=Timeframe.M1)

    assert report.outliers == ()
    assert any("no variation" in note for note in report.notes)


def test_a_spike_is_flagged_suspect_and_left_exactly_as_it_arrived() -> None:
    ranges = {index: Decimal("1.00") + Decimal(index % 7) * Decimal("0.05") for index in range(30)}
    ranges[20] = Decimal("50.00")
    bars = _minute_series(31, ranges=ranges)
    spike = bars[20]

    report = validate_bars(bars, timeframe=Timeframe.M1)

    assert report.status is DataQualityStatus.SUSPECT
    assert report.outliers == (spike.timestamp,)
    assert report.accepted_bars[20] == spike, "the flagged bar was altered"
    assert report.accepted_bars[20].high == Decimal("150.00"), "no clamping happened"
    assert any("not adjusted" in reason for reason in report.reasons)


def test_bars_carrying_a_different_timeframe_than_the_one_validated_are_refused() -> None:
    """Gap arithmetic against the wrong spacing would be a wrong answer."""
    bars = _daily_series(3)

    report = validate_bars(bars, timeframe=Timeframe.M1)

    assert report.status is DataQualityStatus.INVALID
    assert report.accepted_bars == ()
    assert any("timeframe" in reason for reason in report.reasons)


def test_parse_rows_injects_the_symbol_and_timeframe_it_was_given() -> None:
    rows: list[dict[str, object]] = [
        {
            "timestamp": ORIGIN,
            "open": "100.00",
            "high": "101.00",
            "low": "99.00",
            "close": "100.50",
            "volume": "1000",
        }
    ]

    bars = parse_rows(rows, symbol="TEST.NEUTRAL", timeframe=Timeframe.M1)

    assert len(bars) == 1
    assert bars[0].symbol == "TEST.NEUTRAL"
    assert bars[0].timeframe is Timeframe.M1
    assert bars[0].close == Decimal("100.50"), "a price string was coerced rather than parsed"


def test_a_malformed_row_quarantines_the_whole_batch() -> None:
    """One bad row means the payload is not what the provider claimed."""
    rows: list[dict[str, object]] = [
        {
            "timestamp": ORIGIN,
            "open": "100.00",
            "high": "101.00",
            "low": "99.00",
            "close": "100.50",
            "volume": "1000",
        },
        {
            "timestamp": ORIGIN + timedelta(minutes=1),
            "open": "not-a-price",
            "high": "101.00",
            "low": "99.00",
            "close": "100.50",
            "volume": "1000",
        },
    ]

    with pytest.raises(InvalidProviderPayload) as raised:
        parse_rows(rows, symbol="TEST.NEUTRAL", timeframe=Timeframe.M1)

    message = str(raised.value)
    assert "row 1" in message
    assert "open" in message


def test_the_row_that_failed_is_not_echoed_into_the_log_message() -> None:
    """A payload can contain anything; this message ends up in a log."""
    rows: list[dict[str, object]] = [
        {
            "timestamp": "not-a-timestamp",
            "open": "sensitive-value-should-not-appear",
            "high": "101.00",
            "low": "99.00",
            "close": "100.50",
            "volume": "1000",
        }
    ]

    with pytest.raises(InvalidProviderPayload) as raised:
        parse_rows(rows, symbol="TEST.NEUTRAL", timeframe=Timeframe.M1)

    assert "sensitive-value-should-not-appear" not in str(raised.value)


def test_a_report_is_immutable_so_a_status_cannot_be_edited_after_the_fact() -> None:
    report = validate_bars(_minute_series(30), timeframe=Timeframe.M1)

    with pytest.raises(ValidationError, match="frozen"):
        report.status = DataQualityStatus.SUSPECT  # type: ignore[misc]


def test_a_report_refuses_fields_outside_the_contract() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ValidationReport(  # type: ignore[call-arg]
            status=DataQualityStatus.VALID,
            reasons=(),
            notes=(),
            received=0,
            duplicates_removed=0,
            disagreeing_duplicates=0,
            gaps=(),
            outliers=(),
            accepted_bars=(),
            passed=True,
        )
