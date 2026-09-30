"""Version-pinned input data for a backtest.

The engine's data boundary: bars come from the same content-addressed
store the quant recipes read, through the same verification function
(:func:`~harsh_quant_os.quant.recipes.bars.load_stored_bars`) — name
safety, artefact hash against its directory, complete volume — but the
exact ``Decimal`` prices are **kept**, not converted to float64.
backtesting-methodology.md §2: "Cash: exact numerics; no floating-point
money". The price side of money starts as the stored decimal.

:class:`BacktestData` validates at construction so the engine loop can
assume one symbol, one timeframe and strictly increasing
timezone-aware timestamps — the sequencing rules of backtesting.md §2
rest on that assumption being checked, not hoped for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

from harsh_quant_os.backtesting.errors import BacktestError
from harsh_quant_os.data.providers import Bar
from harsh_quant_os.quant.recipes import load_stored_bars

__all__ = ["BacktestData", "WindowCoverage", "load_backtest_data", "window_coverage"]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class BacktestData:
    """One dataset's bars, pinned by content-addressed version.

    Attributes:
        dataset_id: Dataset name, e.g. ``kraken.xbtusd.1m``.
        version: 64-character SHA-256 of the clean artefact — the same
            identity the run manifest records (backtesting.md §4).
        bars: The bars, in stored chronological order, as validated
            ``Bar`` objects (timezone-aware timestamps, exact decimals).

    Raises:
        BacktestError: Empty dataset, missing/invalid pin, more than one
        symbol or timeframe, or timestamps that are not strictly
        increasing (duplicated or out-of-order bars are refused here so
        the engine's strict-time loop never has to guess).
    """

    dataset_id: str
    version: str
    bars: tuple[Bar, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bars", tuple(self.bars))
        if not self.dataset_id or not self.dataset_id.strip():
            raise BacktestError("dataset_id must not be empty")
        if not _SHA256_RE.fullmatch(self.version):
            raise BacktestError(
                f"dataset version must be a 64-character lowercase SHA-256, got {self.version!r}"
            )
        if not self.bars:
            raise BacktestError("a backtest dataset carries at least one bar, got 0")

        symbols = {bar.symbol for bar in self.bars}
        if len(symbols) != 1:
            raise BacktestError(
                f"a backtest runs one instrument; this dataset has {len(symbols)}: "
                + ", ".join(sorted(symbols))
            )
        timeframes = {bar.timeframe for bar in self.bars}
        if len(timeframes) != 1:
            raise BacktestError(
                f"a backtest runs one timeframe; this dataset has "
                f"{len(timeframes)}: " + ", ".join(sorted(tf.value for tf in timeframes))
            )

        for index in range(1, len(self.bars)):
            previous = self.bars[index - 1]
            current = self.bars[index]
            if current.timestamp <= previous.timestamp:
                raise BacktestError(
                    f"bar times must strictly increase: bar {index} at "
                    f"{current.timestamp.isoformat()} does not follow bar {index - 1} at "
                    f"{previous.timestamp.isoformat()} (refused, never reordered)"
                )

    @property
    def start(self) -> datetime:
        """Timestamp of the first bar (timezone-aware)."""
        return self.bars[0].timestamp

    @property
    def end(self) -> datetime:
        """Timestamp of the last bar (timezone-aware)."""
        return self.bars[-1].timestamp

    @property
    def symbol(self) -> str:
        """The dataset's single instrument, e.g. ``XBTUSD``."""
        return self.bars[0].symbol

    @property
    def timeframe(self) -> str:
        """The dataset's timeframe value, e.g. ``1m``."""
        return self.bars[0].timeframe.value

    def span(self, start: int, stop: int) -> BacktestData:
        """The half-open bar span ``[start, stop)``, pinned to this artefact.

        The slice keeps this dataset's id and version: it is the same
        pinned input, cut — never a new dataset with a borrowed name.

        Args:
            start: First bar index (inclusive, non-negative).
            stop: Bar index after the last one (exclusive, at most
                ``len(bars)``).

        Returns:
            A new ``BacktestData`` over the requested bars.

        Raises:
            BacktestError: The span is out of range or empty. An
                absent window fails here rather than quietly becoming
                a shorter one.
        """
        if start < 0 or stop > len(self.bars) or start >= stop:
            raise BacktestError(
                f"bar span [{start}, {stop}) does not exist inside this dataset's "
                f"bars 0..{len(self.bars)} (a missing slice is refused, never "
                "clamped)"
            )
        return BacktestData(
            dataset_id=self.dataset_id, version=self.version, bars=self.bars[start:stop]
        )


def load_backtest_data(root: Path, name: str, *, version: str | None = None) -> BacktestData:
    """Load a stored clean dataset as :class:`BacktestData`.

    Delegates verification to
    :func:`~harsh_quant_os.quant.recipes.bars.load_stored_bars` (its
    refusals — unknown dataset, ambiguous versions, hash mismatch,
    empty, missing volume — propagate unchanged), then applies this
    layer's sequencing validation.

    Args:
        root: The data root (the directory holding ``clean/``).
        name: Dataset name; a plain directory name.
        version: Stored version to load, or ``None`` for the dataset's
            only version.

    Returns:
        The pinned dataset, exact decimals intact.

    Raises:
        RecipeError: Anything the store boundary refuses.
        BacktestError: The bars fail this layer's validation.
    """
    version, bars = load_stored_bars(root, name, version=version)
    return BacktestData(dataset_id=name, version=version, bars=tuple(bars))


@dataclass(frozen=True, slots=True)
class WindowCoverage:
    """How completely the stored bars cover their own span.

    The data-side answer to methodology §5's small-samples and leakage
    rows: before a report quotes anything, it says how much window the
    quote rests on. Missing bars are *counted*, never silently
    interpolated — a gap is a fact about the sample, and a report that
    hid it would misrepresent the evidence.

    Attributes:
        start / end: First and last bar timestamps.
        timeframe: The dataset's timeframe value (e.g. ``1m``).
        nominal_seconds: Fixed bar length in seconds, or ``None`` for
            timeframes with no fixed length (``tick``, ``1mo``) — gap
            analysis is undefined there and reports itself as such.
        actual_bars: Bars stored.
        expected_bars: Bars the span implies at the nominal length
            (inclusive of both ends), or ``None`` when not computable.
        gap_intervals: Intervals wider than one nominal bar, or ``None``.
        missing_bars: Whole bars absent inside those gaps, or ``None``.
        irregular_intervals: Intervals off the nominal grid — closer
            together than one bar, or gaps that do not divide evenly —
            or ``None`` when not computable.
    """

    start: datetime
    end: datetime
    timeframe: str
    nominal_seconds: int | None
    actual_bars: int
    expected_bars: int | None
    gap_intervals: int | None
    missing_bars: int | None
    irregular_intervals: int | None

    @property
    def is_complete(self) -> bool:
        """True only when the count is computable **and** nothing is missing.

        ``None`` (uncomputable) is deliberately not "complete": unknown
        coverage must never read as full coverage.
        """
        return self.missing_bars == 0


_FIXED_UNIT_SECONDS: dict[str, int] = {"m": 60, "h": 3600, "d": 86_400, "w": 604_800}
_FIXED_TIMEFRAME_RE = re.compile(r"^(\d+)([mhdw])$")


def _nominal_seconds(timeframe: str) -> int | None:
    """Fixed bar length in seconds, or ``None`` when it has none.

    ``1mo`` is deliberately not approximated to 30 days: months are not
    fixed lengths, and a gap count computed on a made-up month would be
    a fabricated number (rule zero).
    """
    match = _FIXED_TIMEFRAME_RE.match(timeframe)
    if match is None:
        return None
    return int(match.group(1)) * _FIXED_UNIT_SECONDS[match.group(2)]


def _exact_seconds(delta: timedelta) -> Decimal:
    """A timedelta as exact seconds — no float round-trip on the way."""
    whole = Decimal(delta.days * 86_400 + delta.seconds)
    return whole + Decimal(delta.microseconds) / Decimal(1_000_000)


def window_coverage(data: BacktestData) -> WindowCoverage:
    """Measure how completely the bars cover their own span.

    Walks consecutive bar intervals against the timeframe's nominal
    length: an interval wider than nominal is a gap containing
    ``interval // nominal - 1`` missing bars; intervals that are dense
    or whose gaps do not divide evenly are counted as irregular.

    Args:
        data: The pinned dataset (already validated: strictly
            increasing, timezone-aware, one symbol).

    Returns:
        The coverage record. For a timeframe without a fixed length,
        the computable fields are ``None`` — stated, not estimated.
    """
    bars = data.bars
    nominal = _nominal_seconds(data.timeframe)
    start, end = bars[0].timestamp, bars[-1].timestamp
    if nominal is None:
        return WindowCoverage(
            start=start,
            end=end,
            timeframe=data.timeframe,
            nominal_seconds=None,
            actual_bars=len(bars),
            expected_bars=None,
            gap_intervals=None,
            missing_bars=None,
            irregular_intervals=None,
        )

    nominal_decimal = Decimal(nominal)
    span = _exact_seconds(end - start)
    expected = int(span // nominal_decimal) + 1

    gap_intervals = 0
    missing_bars = 0
    irregular_intervals = 0
    for previous, current in pairwise(bars):
        spacing = _exact_seconds(current.timestamp - previous.timestamp)
        if spacing > nominal_decimal:
            gap_intervals += 1
            missing_bars += int(spacing // nominal_decimal) - 1
            if spacing % nominal_decimal != 0:
                irregular_intervals += 1
        elif spacing < nominal_decimal:
            # Strictly positive (timestamps increase) and below one bar:
            # dense and/or off the grid either way.
            irregular_intervals += 1

    return WindowCoverage(
        start=start,
        end=end,
        timeframe=data.timeframe,
        nominal_seconds=nominal,
        actual_bars=len(bars),
        expected_bars=expected,
        gap_intervals=gap_intervals,
        missing_bars=missing_bars,
        irregular_intervals=irregular_intervals,
    )
