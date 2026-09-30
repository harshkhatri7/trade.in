"""Regime segmentation: results split by the market they were earned in.

anti-overfitting.md §2.7: "Split results by volatility/trend/liquidity
regime. A strategy that only works in one regime is reported as
regime-specific, not as general." backtesting-methodology.md carries
the same row: results split by regime.

Design commitments:

- **Labels are causal.** A bar's label is a function of that bar and
  the trailing ``window`` bars behind it — never of the bars ahead.
  Thresholds are DECLARED inputs, never quantiles of the whole sample:
  a whole-sample quantile reads the future, so the built-ins here take
  their thresholds as arguments.
- **Warm bars are ``undefined``, not guessed.** Until a full trailing
  window exists there is no label to give; those bars are their own
  segment and counted, never folded into a neighbouring regime.
- **The rule travels with the labels.** :class:`RegimeLabels` carries
  the human-readable rule beside the per-bar labels, and
  :class:`RegimeSplit` keeps it: a split reported without the rule
  that produced it would be a metric without its assumptions.
- **Attribution is by entry.** A completed cycle is attributed to the
  regime in force when the position was OPENED — the decision point —
  and stated as such: a trade can span regimes, and its P&L is not
  split to pretend otherwise. The position still open at the end is
  counted under its entry regime, and its outcome sits in no cycle's
  P&L (the metric set's rule: an unclosed trade is neither win nor
  loss).
- **The split is retrospective reporting, not selection.** Nothing is
  re-run, re-tuned or dropped: the same run's cycles, grouped. A
  profitable run whose gains all entered in one regime reports
  ``regime_specific`` — regime-specific, not general.

Any labels may be supplied (liquidity or a custom rule included) as
long as they are one non-empty string per bar of the run; the two
built-ins are volatility and trend, both exact ``Decimal`` with the
quant package's population-variance convention (ddof=0).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from harsh_quant_os.backtesting.data import BacktestData
from harsh_quant_os.backtesting.engine import BacktestResult
from harsh_quant_os.backtesting.errors import BacktestError
from harsh_quant_os.backtesting.metrics import trade_records
from harsh_quant_os.backtesting.report import wilson_interval

__all__ = [
    "UNDEFINED",
    "RegimeLabels",
    "RegimeSegment",
    "RegimeSplit",
    "split_by_regime",
    "trend_regimes",
    "volatility_regimes",
]

#: The label for bars with no trailing window yet — a segment of its
#: own in every split, so the warm period is visible rather than
#: quietly absorbed into whatever regime follows it.
UNDEFINED = "undefined"


def _as_finite_decimal(value: object, *, label: str) -> Decimal:
    """Refuse anything that is not a finite Decimal (no float reaches a rule)."""
    if not isinstance(value, Decimal):
        raise BacktestError(
            f"{label} must be a Decimal, got {type(value).__name__} "
            "(no float reaches a regime rule)"
        )
    if not value.is_finite():
        raise BacktestError(f"{label} must be finite, got {value}")
    return value


def _check_window(data: BacktestData, window: int, *, minimum: int) -> None:
    """The trailing window must fit the data and mean what it says."""
    if window < minimum:
        raise BacktestError(
            f"a trailing window of {window} is too small (at least {minimum} "
            "needed): a shorter window cannot mean what the rule claims"
        )
    if window > len(data.bars) - 1:
        raise BacktestError(
            f"a trailing window of {window} returns cannot fit in "
            f"{len(data.bars)} bars ({len(data.bars) - 1} returns): no bar "
            "would carry a label, and an all-undefined split is refused"
        )


def _closes(data: BacktestData) -> list[Decimal]:
    """The closes, refusing non-positive prices the ratios could not use."""
    closes = [bar.close for bar in data.bars]
    for index, close in enumerate(closes):
        if close <= 0:
            raise BacktestError(
                f"bar {index} closes at {close}: close-to-close ratios need "
                "positive prices, and this one would divide by it"
            )
    return closes


def volatility_regimes(data: BacktestData, *, window: int, threshold: Decimal) -> RegimeLabels:
    """Label bars by trailing volatility against a declared threshold.

    The rule: over the trailing ``window`` close-to-close simple
    returns ending at this bar (population standard deviation, ddof=0
    — the quant package's convention), ``high_vol`` when the deviation
    is strictly above ``threshold`` and ``low_vol`` otherwise. Bars
    without a full trailing window are ``undefined``.

    Args:
        data: The pinned bars being labelled.
        window: Trailing number of returns (at least 2 — one return
            has no dispersion, and calling it zero would invent one).
        threshold: Declared volatility level, a finite non-negative
            ``Decimal``.

    Returns:
        The rule and one label per bar.

    Raises:
        BacktestError: Window smaller than 2, a window that cannot fit
        the data, a non-Decimal or non-finite or negative threshold,
        or a non-positive close.
    """
    threshold = _as_finite_decimal(threshold, label="threshold")
    if threshold < 0:
        raise BacktestError(
            f"a volatility threshold is a dispersion: {threshold} is "
            "negative — refusing a rule that cannot mean what it says"
        )
    _check_window(data, window, minimum=2)
    closes = _closes(data)

    returns = [closes[index] / closes[index - 1] - 1 for index in range(1, len(closes))]
    labels: list[str] = [UNDEFINED] * window
    count = Decimal(window)
    for index in range(window, len(closes)):
        trailing = returns[index - window : index]
        mean = sum(trailing, Decimal(0)) / count
        variance = sum((value - mean) ** 2 for value in trailing) / count
        deviation = variance.sqrt()
        labels.append("high_vol" if deviation > threshold else "low_vol")

    return RegimeLabels(
        rule=(
            f"trailing {window}-bar population stdev of close-to-close returns "
            f"> {threshold} -> high_vol, else low_vol; the first {window} "
            "bars are undefined (no trailing window yet)"
        ),
        labels=tuple(labels),
    )


def trend_regimes(
    data: BacktestData, *, window: int, up_threshold: Decimal, down_threshold: Decimal
) -> RegimeLabels:
    """Label bars by trailing trend against two declared thresholds.

    The rule: the close-to-close return over the trailing ``window``
    bars (``close[i] / close[i-window] - 1``) is ``up`` when strictly
    above ``up_threshold``, ``down`` when strictly below
    ``-down_threshold``, otherwise ``ranging``. Bars without a full
    trailing window are ``undefined``.

    Args:
        data: The pinned bars being labelled.
        window: Trailing number of bars (at least 1).
        up_threshold: Declared up-move magnitude, finite ``Decimal``
            at least zero.
        down_threshold: Declared down-move magnitude, finite
            ``Decimal`` at least zero.

    Returns:
        The rule and one label per bar.

    Raises:
        BacktestError: Window smaller than 1, a window that cannot fit
        the data, a threshold that is not a finite non-negative
        ``Decimal``, or a non-positive close.
    """
    up_threshold = _as_finite_decimal(up_threshold, label="up_threshold")
    down_threshold = _as_finite_decimal(down_threshold, label="down_threshold")
    for label, value in (("up_threshold", up_threshold), ("down_threshold", down_threshold)):
        if value < 0:
            raise BacktestError(
                f"{label} is a magnitude compared against a signed return: "
                f"{value} is negative — refusing a rule that cannot mean "
                "what it says"
            )
    _check_window(data, window, minimum=1)
    closes = _closes(data)

    labels: list[str] = [UNDEFINED] * window
    for index in range(window, len(closes)):
        move = closes[index] / closes[index - window] - 1
        if move > up_threshold:
            labels.append("up")
        elif move < -down_threshold:
            labels.append("down")
        else:
            labels.append("ranging")

    return RegimeLabels(
        rule=(
            f"return over the trailing {window} bar(s) > {up_threshold} -> up, "
            f"< -{down_threshold} -> down, else ranging; the first {window} "
            "bars are undefined (no trailing window yet)"
        ),
        labels=tuple(labels),
    )


@dataclass(frozen=True, slots=True)
class RegimeLabels:
    """One label per bar, with the rule that produced them.

    Attributes:
        rule: The causal rule in words, kept beside the labels so a
            split can always say what it split by.
        labels: One non-empty label per bar of the same dataset the
            split will cover.

    Raises:
        BacktestError: Empty rule, no labels, or an empty label.
    """

    rule: str
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.rule.strip():
            raise BacktestError(
                "regime labels must carry the rule that produced them: a "
                "split without its rule is a metric without its assumptions"
            )
        if not self.labels:
            raise BacktestError("regime labels cover at least one bar")
        for label in self.labels:
            if not label:
                raise BacktestError(f"a regime label must not be empty: {self.labels!r}")


@dataclass(frozen=True, slots=True)
class RegimeSegment:
    """One regime's share of a run: bars, cycles, and their outcomes.

    Attributes:
        label: The regime's name.
        bars: Bars carrying this label.
        trades: Completed cycles whose ENTRY bar carried this label.
        wins / losses / breakeven: Those cycles split by sign
            (breakeven excluded from the hit rate, as §4 rules).
        open_at_end: Positions opened under this label still open at
            the run's final bar — counted, but in no cycle's P&L.
        realised: Exact realised P&L of those completed cycles (fees
            included — the ledger's own arithmetic).
        hit_rate: wins / (wins + losses), or ``None`` when no cycle
            completed (never a plausible zero).
        hit_interval: The Wilson 95% interval for that rate, or
            ``None`` when there were no trials.

    Raises:
        BacktestError: Counts that do not add up, a non-finite
        realised, or a negative count.
    """

    label: str
    bars: int
    trades: int
    wins: int
    losses: int
    breakeven: int
    open_at_end: int
    realised: Decimal
    hit_rate: Decimal | None = field(init=False)
    hit_interval: tuple[Decimal, Decimal] | None = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("bars", self.bars),
            ("trades", self.trades),
            ("wins", self.wins),
            ("losses", self.losses),
            ("breakeven", self.breakeven),
            ("open_at_end", self.open_at_end),
        ):
            if value < 0:
                raise BacktestError(f"a regime segment's {name} cannot be negative, got {value}")
        if self.bars == 0:
            raise BacktestError(
                f"regime {self.label!r} has no bars: a segment exists only if the split found it"
            )
        if self.wins + self.losses + self.breakeven != self.trades:
            raise BacktestError(
                f"regime {self.label!r}: {self.wins} wins + {self.losses} losses + "
                f"{self.breakeven} breakeven != {self.trades} trades"
            )
        if not self.realised.is_finite():
            raise BacktestError(
                f"regime {self.label!r}: realised must be a finite decimal, got {self.realised}"
            )
        decided = self.wins + self.losses
        rate: Decimal | None = None
        interval: tuple[Decimal, Decimal] | None = None
        if decided > 0:
            rate = Decimal(self.wins) / Decimal(decided)
            interval = wilson_interval(self.wins, decided)
        object.__setattr__(self, "hit_rate", rate)
        object.__setattr__(self, "hit_interval", interval)


@dataclass(frozen=True, slots=True)
class RegimeSplit:
    """A run's cycles grouped by the regime in force when they entered.

    Attributes:
        rule: The causal labelling rule (kept from the labels).
        segments: One per distinct label, in order of first
            appearance on the run's bars.
        bars: Total bars covered (sum of the segments').
        completed: Total completed cycles (sum of the segments').
        open_positions: Positions still open at the end — at most one
            (one instrument holds one position).
        realised: Total realised P&L of the completed cycles; equals
            the segments' sum, and equals the run's recorded realised
            total whenever the run ended flat.

    Raises:
        BacktestError: A split that cannot account for itself —
        missing sums, a repeated segment label, or more open
        positions than one instrument can hold.
    """

    rule: str
    segments: tuple[RegimeSegment, ...]
    bars: int
    completed: int
    open_positions: int
    realised: Decimal

    def __post_init__(self) -> None:
        if not self.segments:
            raise BacktestError("a regime split carries at least one segment")
        seen: set[str] = set()
        for segment in self.segments:
            if segment.label in seen:
                raise BacktestError(
                    f"regime {segment.label!r} appears twice: segments are one per distinct label"
                )
            seen.add(segment.label)
        expected = (
            (self.bars, sum(segment.bars for segment in self.segments), "bars"),
            (self.completed, sum(segment.trades for segment in self.segments), "completed cycles"),
            (
                self.open_positions,
                sum(segment.open_at_end for segment in self.segments),
                "open positions",
            ),
        )
        for recorded, computed, what in expected:
            if recorded != computed:
                raise BacktestError(
                    f"the split records {recorded} {what} but its segments "
                    f"account for {computed}: a split that cannot account for "
                    "itself is refused, not smoothed over"
                )
        if self.open_positions > 1:
            raise BacktestError(
                f"one instrument holds one position at the end, got "
                f"{self.open_positions} open at the close"
            )
        total = Decimal(0)
        for segment in self.segments:
            total += segment.realised
        if total != self.realised:
            raise BacktestError(
                f"the split records realised {self.realised} but its segments "
                f"sum to {total}: a split that cannot account for itself is "
                "refused, not smoothed over"
            )

    @property
    def undefined_bars(self) -> int:
        """Bars that had no trailing window yet (``undefined`` segment)."""
        for segment in self.segments:
            if segment.label == UNDEFINED:
                return segment.bars
        return 0

    @property
    def positive_regimes(self) -> int:
        """Segments whose realised P&L is above zero."""
        return sum(1 for segment in self.segments if segment.realised > 0)

    @property
    def regime_specific(self) -> bool:
        """All the profit entered under exactly one regime.

        A profitable split with more than one regime where gains came
        from only one of them reports ``True``: the run worked in one
        regime, so it is reported as regime-specific rather than as a
        general edge (anti-overfitting §2.7).
        """
        return self.realised > 0 and self.positive_regimes == 1 and len(self.segments) > 1


def split_by_regime(result: BacktestResult, labels: RegimeLabels) -> RegimeSplit:
    """Group a finished run's cycles by the regime of their entry bar.

    Args:
        result: The finished run — its own ledger is walked, so the
            split cannot disagree with the run's recorded numbers.
        labels: One label per bar of the run's dataset, with the rule.

    Returns:
        The split: segments in first-appearance order, with the rule
        kept beside them.

    Raises:
        BacktestError: Label count that is not the run's bar count (a
        different window's labels are refused, not zipped), a bar time
        the labels cannot map to, a cycle whose entry is not one of
        the run's own bar times, or a result whose flat-ending totals
        its own ledger walk cannot reproduce.
    """
    curve = result.equity_curve
    if len(labels.labels) != len(curve):
        raise BacktestError(
            f"labels cover {len(labels.labels)} bars but the run marks "
            f"{len(curve)}: the split attributes the run's own cycles to its "
            "own bars — labels from another window are refused, not zipped"
        )
    index_of: dict[object, int] = {}
    for index, point in enumerate(curve):
        if point.time in index_of:
            raise BacktestError(
                f"the run's curve carries {point.time.isoformat()} twice; "
                "attribution needs one bar per time"
            )
        index_of[point.time] = index

    def bar_index(at: object, *, what: str) -> int:
        try:
            return index_of[at]
        except (KeyError, TypeError) as error:
            time_text = at.isoformat() if isinstance(at, datetime) else repr(at)
            raise BacktestError(
                f"{what} at {time_text} is not one of the run's bar times; "
                "attribution is refused rather than nearest-matched"
            ) from error

    order: list[str] = []
    seen: set[str] = set()
    for label in labels.labels:
        if label not in seen:
            seen.add(label)
            order.append(label)

    bars_by_label = dict.fromkeys(order, 0)
    trades_by_label = dict.fromkeys(order, 0)
    wins_by_label = dict.fromkeys(order, 0)
    losses_by_label = dict.fromkeys(order, 0)
    breakeven_by_label = dict.fromkeys(order, 0)
    open_by_label = dict.fromkeys(order, 0)
    realised_by_label = {label: Decimal(0) for label in order}
    for label in labels.labels:
        bars_by_label[label] += 1

    records = trade_records(result)
    for trip in records.completed:
        label = labels.labels[bar_index(trip.entry, what="a cycle's entry")]
        trades_by_label[label] += 1
        realised_by_label[label] += trip.pnl
        if trip.pnl > 0:
            wins_by_label[label] += 1
        elif trip.pnl < 0:
            losses_by_label[label] += 1
        else:
            breakeven_by_label[label] += 1
    if records.open_entry is not None:
        label = labels.labels[bar_index(records.open_entry, what="the open position's entry")]
        open_by_label[label] += 1

    segments = tuple(
        RegimeSegment(
            label=label,
            bars=bars_by_label[label],
            trades=trades_by_label[label],
            wins=wins_by_label[label],
            losses=losses_by_label[label],
            breakeven=breakeven_by_label[label],
            open_at_end=open_by_label[label],
            realised=realised_by_label[label],
        )
        for label in order
    )

    realised = Decimal(0)
    for segment in segments:
        realised += segment.realised
    if records.open_entry is None and realised != result.realised_pnl:
        raise BacktestError(
            f"the split's cycles account for {realised} but the run recorded "
            f"realised {result.realised_pnl}: a result whose own numbers "
            "disagree with its ledger is refused, not smoothed over"
        )

    return RegimeSplit(
        rule=labels.rule,
        segments=segments,
        bars=len(curve),
        completed=len(records.completed),
        open_positions=0 if records.open_entry is None else 1,
        realised=realised,
    )
