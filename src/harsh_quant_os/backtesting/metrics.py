"""Performance metrics derived from one recorded run — assumptions attached.

backtesting-methodology.md §4 lists what is *always* reported: total and
annualised return with the compounding convention stated, volatility and
Sharpe with frequency and risk-free assumption stated, maximum drawdown
and time under water, trade count and median holding period, turnover
and total costs, exposure (gross/net) and concentration, and hit rate
**with** the distribution of win/loss sizes. The closing rule of that
section governs this module: *a metric without its assumptions is not
reported* — every function's output therefore carries an ``assumptions``
tuple, and anything undefined (zero volatility, no completed trade) is
``None`` rather than a plausible-looking number.

Conventions chosen here, each also recorded in ``assumptions``:

- **Money stays exact.** Equity, drawdown amounts, round-trip P&L and
  costs are ``Decimal`` arithmetic over the result's own numbers; ratios
  are exact decimal divisions of them. No float touches a figure.
- **Annualisation uses actual elapsed time**, not a nominal bar count:
  years = seconds between first and last bar ÷ 31,536,000 (365-day
  year). A gapped sample annualises over the time it actually spans —
  gaps cannot silently inflate a rate.
- **Returns are simple per-bar equity returns**; volatility is their
  population standard deviation (ddof=0, matching the quant package's
  rolling convention), scaled by the square root of bar frequency.
- **Sharpe assumes a zero risk-free rate** (stated, not fitted) and is
  annualised as mean/std * sqrt(bars per elapsed year).
- **Round trips**: one open-to-close cycle; a position still open at
  the sample's end is not a completed trade; the walk reuses the
  engine's own :class:`~harsh_quant_os.backtesting.ledger.Ledger`, so
  per-trip P&L is the same arithmetic the result's realised total is.

Metrics read only the finished :class:`BacktestResult` — they cannot
see anything the engine did not already record, so computing them
later (or twice) cannot become a look-ahead.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from harsh_quant_os.backtesting.engine import BacktestResult
from harsh_quant_os.backtesting.errors import BacktestError
from harsh_quant_os.backtesting.ledger import Ledger

__all__ = [
    "CostStats",
    "DrawdownStats",
    "ExposureStats",
    "RoundTrip",
    "RunMetrics",
    "TradeRecords",
    "TradeStats",
    "VolatilityStats",
    "compute_metrics",
    "trade_records",
]

#: Seconds in the 365-day year the annualisation convention uses.
_YEAR_SECONDS = Decimal(31_536_000)

_ZERO = Decimal(0)


# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VolatilityStats:
    """Annualised volatility and Sharpe — ``None`` when undefined.

    Attributes:
        annualised: Population std-dev of per-bar returns, scaled by
            sqrt(bars/year), or ``None`` when the sample has no
            dispersion to measure.
        sharpe: Annualised mean/std (risk-free 0), or ``None``.
        note: Why either is ``None`` (``""`` when both are reported).
    """

    annualised: Decimal | None
    sharpe: Decimal | None
    note: str


@dataclass(frozen=True, slots=True)
class DrawdownStats:
    """Peak-to-trough drawdown on marked equity, and its under water time.

    Attributes:
        max_drawdown: Deepest peak-to-trough fall as a ratio of the
            peak (0 when the curve never fell).
        max_drawdown_amount: The same drawdown in exact money.
        peak_time: Bar whose equity set the running high the fall
            started from (``None`` when there was no drawdown).
        trough_time: Bar of the deepest fall (``None`` when none).
        time_under_water: Peak to recovery, or peak to sample end when
            the peak was never regained (``None`` when no drawdown).
        recovered: Whether equity regained the peak within the sample.
    """

    max_drawdown: Decimal
    max_drawdown_amount: Decimal
    peak_time: datetime | None
    trough_time: datetime | None
    time_under_water: timedelta | None
    recovered: bool


@dataclass(frozen=True, slots=True)
class TradeStats:
    """Completed round trips: counts, hit rate, holding, size distribution.

    Attributes:
        round_trips: Open-to-close cycles completed in the sample.
        wins / losses / breakeven: Split of round-trip P&L by sign.
        hit_rate: ``wins / (wins + losses)``, breakeven excluded —
            ``None`` when no round trip completed (nothing to hit).
        median_holding: Median entry-fill to flat-fill duration over
            completed trips (microsecond resolution; ``None`` when
            none completed).
        pnls: Round-trip P&L in chronological order (exact), for the
            distribution a bare hit rate would hide.
        median_win / mean_win / min_win / max_win: Distribution of
            winning sizes (``None`` when there are none).
        median_loss / mean_loss / min_loss / max_loss: Distribution of
            losing sizes, as negative numbers (``None`` when none).
        open_position_at_end: A position was still held at the final
            bar — its outcome is not in these numbers.
    """

    round_trips: int
    wins: int
    losses: int
    breakeven: int
    hit_rate: Decimal | None
    median_holding: timedelta | None
    pnls: tuple[Decimal, ...]
    median_win: Decimal | None
    mean_win: Decimal | None
    min_win: Decimal | None
    max_win: Decimal | None
    median_loss: Decimal | None
    mean_loss: Decimal | None
    min_loss: Decimal | None
    max_loss: Decimal | None
    open_position_at_end: bool


@dataclass(frozen=True, slots=True)
class CostStats:
    """What the run paid to trade, and how much it turned over.

    Attributes:
        commission: Fees charged on fills (exact).
        slippage: Money given away to the slippage model —
            ``sum((fill - reference) * delta)``, positive under a
            pessimistic model (exact).
        total: commission + slippage (exact).
        turnover: Gross traded notional / starting equity (exact
            ratio).
    """

    commission: Decimal
    slippage: Decimal
    total: Decimal
    turnover: Decimal


@dataclass(frozen=True, slots=True)
class ExposureStats:
    """How much was held, for how long, and how concentrated.

    Attributes:
        gross_time: Fraction of bars whose post-fill position was
            non-zero.
        net_equity_ratio: sum(position * close) / sum(equity) across
            bars — average net exposure as a fraction of equity
            (signed; a short book reads negative).
        peak_concentration: Largest single-bar |position * close| as a
            fraction of equity (single-instrument book: how close the
            whole account came to being one position).
    """

    gross_time: Decimal
    net_equity_ratio: Decimal
    peak_concentration: Decimal


@dataclass(frozen=True, slots=True)
class RunMetrics:
    """The §4 metric set for one run, assumptions included.

    Attributes:
        total_return: ending equity / starting equity - 1 (exact).
        annualised_return: total return annualised over actual elapsed
            time (exact decimal power).
        sample_years: Elapsed time of the sample in 365-day years
            (the annualisation denominator, recorded so the reader can
            see how short "annualised" really is).
        volatility: See :class:`VolatilityStats`.
        drawdown: See :class:`DrawdownStats`.
        trades: See :class:`TradeStats`.
        costs: See :class:`CostStats`.
        exposure: See :class:`ExposureStats`.
        assumptions: Keyed conventions this metric set was computed
            under — sorted, so the bytes never depend on insertion
            order. §4: a metric without its assumptions is not
            reported.
    """

    total_return: Decimal
    annualised_return: Decimal
    sample_years: Decimal
    volatility: VolatilityStats
    drawdown: DrawdownStats
    trades: TradeStats
    costs: CostStats
    exposure: ExposureStats
    assumptions: tuple[tuple[str, str], ...]


# ---------------------------------------------------------------------------
# Small exact helpers
# ---------------------------------------------------------------------------


def _seconds(delta: timedelta) -> Decimal:
    """A timedelta as exact seconds (no float round-trip)."""
    whole = Decimal(delta.days * 86_400 + delta.seconds)
    return whole + Decimal(delta.microseconds) / Decimal(1_000_000)


def _median_decimal(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _median_timedelta(values: Sequence[timedelta]) -> timedelta:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _annualise(ratio_base: Decimal, years: Decimal, *, what: str) -> Decimal:
    """``ratio_base ** (1/years)`` — refuse overflow instead of guessing."""
    try:
        return ratio_base ** (Decimal(1) / years) - 1
    except ArithmeticError as error:
        raise BacktestError(
            f"{what} is unrepresentable for this sample (elapsed {years} "
            "years): refusing to report a figure decimal arithmetic cannot "
            "hold"
        ) from error


def _distribution(
    sizes: Sequence[Decimal],
) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
    """(median, mean, min, max) of a size sample — four ``None``s when empty."""
    if not sizes:
        return None, None, None, None
    return (
        _median_decimal(sizes),
        sum(sizes, _ZERO) / Decimal(len(sizes)),
        min(sizes),
        max(sizes),
    )


# ---------------------------------------------------------------------------
# The walk of a result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoundTrip:
    """One completed open-to-close cycle, with the times that made it.

    Attributes:
        entry: Fill time that opened the cycle.
        exit: Fill time that closed it.
        holding: ``exit - entry``.
        pnl: Realised P&L of the cycle, exact — the same ledger
            arithmetic the run's realised total was built with.
    """

    entry: datetime
    exit: datetime
    holding: timedelta
    pnl: Decimal


@dataclass(frozen=True, slots=True)
class TradeRecords:
    """A result's cycles as the ledger reconstructed them.

    Attributes:
        completed: Every closed cycle, in the order they closed.
        open_entry: The fill time that opened the position still held
            at the run's final bar, or ``None`` when the run ended
            flat. Its outcome is in no cycle's ``pnl`` — the metric
            set never counts an unclosed trade as a win or a loss.
    """

    completed: tuple[RoundTrip, ...]
    open_entry: datetime | None


def trade_records(result: BacktestResult) -> TradeRecords:
    """Replay fills through the engine's ledger, recording entry times.

    One walk, one implementation: :func:`compute_metrics` and the
    regime split read the same reconstruction, so they cannot drift
    apart. Uses the very arithmetic the result's realised total was
    built with, so completed cycles' P&Ls sum to the recorded total
    for flat-ending runs (a run ending with the position open has an
    unclosed cycle in ``open_entry`` instead).

    Raises:
        BacktestError: A FILLED order without a fill time, or a
            position that closed with no recorded entry — a result
            that cannot be walked is refused, not summarised.
    """
    ledger = Ledger(result.starting_capital)
    fills = sorted(result.filled, key=lambda order: order.fill_time or order.decision_time)

    trips: list[RoundTrip] = []
    entry_time: datetime | None = None
    trip_pnl = _ZERO
    previous = ledger.quantity

    for fill in fills:
        at = fill.fill_time
        price = fill.fill_price
        if at is None or price is None:
            raise BacktestError(
                "a FILLED order has no fill time or price; round trips "
                "cannot be reconstructed from this result"
            )
        was_open = previous != 0
        before = ledger.realised_pnl
        ledger.apply_fill(price, fill.delta, fill.commission)
        added = ledger.realised_pnl - before
        now = ledger.quantity
        crossing = (
            was_open and ((fill.delta > 0) != (previous > 0)) and abs(fill.delta) > abs(previous)
        )

        if was_open:
            trip_pnl += added
            if now == 0 or crossing:
                if entry_time is None:
                    raise BacktestError(
                        "a position closed with no recorded entry fill; round "
                        "trips cannot be reconstructed from this result"
                    )
                trips.append(
                    RoundTrip(
                        entry=entry_time,
                        exit=at,
                        holding=at - entry_time,
                        pnl=trip_pnl,
                    )
                )
                trip_pnl = _ZERO
                entry_time = at if now != 0 else None
        elif now != 0:
            entry_time = at
        previous = now

    return TradeRecords(completed=tuple(trips), open_entry=entry_time)


def _round_trips(result: BacktestResult) -> tuple[list[Decimal], list[timedelta]]:
    """The pair compute_metrics reads: cycle P&Ls and their holdings."""
    records = trade_records(result)
    return [trip.pnl for trip in records.completed], [trip.holding for trip in records.completed]


def _assumptions() -> tuple[tuple[str, str], ...]:
    """Every convention this computation uses, keyed and sorted."""
    entries = {
        "annualisation": (
            "actual elapsed time between first and last bar; 365-day year "
            "(31,536,000 s); gaps are not filled or interpolated"
        ),
        "compounding": (
            "total return = ending equity / starting equity - 1 "
            "(equity-curve convention; no per-trade compounding assumed)"
        ),
        "concentration": ("peak over bars of |position * close| / equity (single-instrument book)"),
        "costs": (
            "commission paid plus slippage money sum((fill - reference) * "
            "delta); borrow, financing and funding are explicitly not "
            "modelled by this engine"
        ),
        "drawdown": (
            "peak-to-trough on marked equity; the peak is the last bar that "
            "set a new equity high; time under water runs from that peak to "
            "recovery or sample end"
        ),
        "exposure_gross": "fraction of bars whose post-fill position is non-zero",
        "exposure_net": "sum(position * close) / sum(equity) across bars",
        "hit_rate": (
            "wins / (wins + losses); breakeven round trips excluded; None "
            "when no round trip completed"
        ),
        "holding_period": (
            "entry fill to the fill that returned the position to flat; "
            "median over completed round trips; microsecond resolution"
        ),
        "risk_free_rate": "0 (stated, not estimated)",
        "sharpe": (
            "annualised: mean/std of simple per-bar equity returns * "
            "sqrt(bars per elapsed year); None when volatility is zero"
        ),
        "trades": (
            "a round trip is one open-to-close cycle; a position still open "
            "at the sample's end is not a completed trade"
        ),
        "turnover": "gross traded notional / starting equity",
        "volatility": (
            "population standard deviation (ddof=0, matching the quant "
            "package convention) of simple per-bar equity returns, "
            "annualised by sqrt(bar frequency)"
        ),
    }
    return tuple(sorted(entries.items()))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def compute_metrics(result: BacktestResult) -> RunMetrics:
    """Derive the §4 metric set from a finished run's own record.

    Args:
        result: The run to summarise (orders + equity curve only — no
            external data, no future information).

    Returns:
        The metrics with their assumptions.

    Raises:
        BacktestError: Fewer than two equity points, non-positive
            equity or a non-positive close (ratio metrics would be
            undefined), an unrepresentable annualisation, or a result
            whose fills cannot be walked into round trips.
    """
    curve = result.equity_curve
    if len(curve) < 2:
        raise BacktestError(f"metrics need at least two equity points, got {len(curve)}")

    equities = [point.equity for point in curve]
    for point in curve:
        if point.equity <= _ZERO:
            raise BacktestError(
                f"equity is {point.equity} at {point.time.isoformat()}: ratio "
                "metrics are undefined on a non-positive account, and this "
                "refusal is stated rather than reported as a number"
            )
        if point.close <= _ZERO:
            raise BacktestError(
                f"close is {point.close} at {point.time.isoformat()}: "
                "exposure ratios over a non-positive price are undefined"
            )

    starting = result.starting_capital
    if starting <= _ZERO:
        raise BacktestError(f"starting capital must be positive, got {starting}")

    # --- returns, frequency, annualisation --------------------------------
    elapsed = _seconds(curve[-1].time - curve[0].time)
    if elapsed <= _ZERO:
        raise BacktestError("sample spans zero time; annualisation is undefined")
    years = elapsed / _YEAR_SECONDS

    total_return = result.ending_equity / starting - 1
    annualised_return = _annualise(result.ending_equity / starting, years, what="annualised return")

    returns = [equities[index] / equities[index - 1] - 1 for index in range(1, len(equities))]
    count = Decimal(len(returns))
    mean = sum(returns, _ZERO) / count
    variance = sum((value - mean) ** 2 for value in returns) / count  # ddof=0
    per_bar_sigma = variance.sqrt()
    bar_frequency = count / years

    if per_bar_sigma == _ZERO:
        volatility = VolatilityStats(
            annualised=None,
            sharpe=None,
            note=(
                "per-bar returns have zero dispersion over this sample; "
                "volatility and Sharpe are undefined, not zero"
            ),
        )
    else:
        volatility = VolatilityStats(
            annualised=per_bar_sigma * bar_frequency.sqrt(),
            sharpe=(mean / per_bar_sigma) * bar_frequency.sqrt(),
            note="",
        )

    # --- drawdown ---------------------------------------------------------
    peak = equities[0]
    peak_time = curve[0].time
    max_drawdown = _ZERO
    max_amount = _ZERO
    dd_peak_value: Decimal | None = None
    dd_peak_time: datetime | None = None
    dd_trough_time: datetime | None = None
    trough_index = -1

    for index, equity in enumerate(equities):
        if equity > peak:
            peak = equity
            peak_time = curve[index].time
        drawdown = (peak - equity) / peak
        if drawdown > max_drawdown:
            max_drawdown = drawdown
            max_amount = peak - equity
            dd_peak_value = peak
            dd_peak_time = peak_time
            dd_trough_time = curve[index].time
            trough_index = index

    if dd_peak_time is None or dd_trough_time is None or dd_peak_value is None:
        drawdown_stats = DrawdownStats(
            max_drawdown=_ZERO,
            max_drawdown_amount=_ZERO,
            peak_time=None,
            trough_time=None,
            time_under_water=None,
            recovered=True,  # nothing fell; nothing to recover
        )
    else:
        recovery_time = next(
            (
                curve[index].time
                for index in range(trough_index + 1, len(curve))
                if equities[index] >= dd_peak_value
            ),
            None,
        )
        drawdown_stats = DrawdownStats(
            max_drawdown=max_drawdown,
            max_drawdown_amount=max_amount,
            peak_time=dd_peak_time,
            trough_time=dd_trough_time,
            time_under_water=(
                (recovery_time - dd_peak_time)
                if recovery_time is not None
                else (curve[-1].time - dd_peak_time)
            ),
            recovered=recovery_time is not None,
        )

    # --- trades -----------------------------------------------------------
    pnls, holdings = _round_trips(result)
    win_sizes = [pnl for pnl in pnls if pnl > 0]
    loss_sizes = [pnl for pnl in pnls if pnl < 0]
    breakeven = sum(1 for pnl in pnls if pnl == 0)
    denominator = len(win_sizes) + len(loss_sizes)

    (
        median_win,
        mean_win,
        min_win,
        max_win,
    ) = _distribution(win_sizes)
    (
        median_loss,
        mean_loss,
        min_loss,
        max_loss,
    ) = _distribution(loss_sizes)

    trades = TradeStats(
        round_trips=len(pnls),
        wins=len(win_sizes),
        losses=len(loss_sizes),
        breakeven=breakeven,
        hit_rate=(Decimal(len(win_sizes)) / Decimal(denominator) if denominator else None),
        median_holding=_median_timedelta(holdings) if holdings else None,
        pnls=tuple(pnls),
        median_win=median_win,
        mean_win=mean_win,
        min_win=min_win,
        max_win=max_win,
        median_loss=median_loss,
        mean_loss=mean_loss,
        min_loss=min_loss,
        max_loss=max_loss,
        open_position_at_end=result.ending_quantity != 0,
    )

    # --- costs and turnover ----------------------------------------------
    slippage_money = _ZERO
    traded_notional = _ZERO
    for order in result.filled:
        if order.fill_price is None or order.reference_open is None:
            raise BacktestError(
                "a FILLED order lacks its fill or reference price; costs "
                "cannot be reconstructed from this result"
            )
        slippage_money += (order.fill_price - order.reference_open) * order.delta
        traded_notional += abs(order.delta * order.fill_price)

    costs = CostStats(
        commission=result.total_commission,
        slippage=slippage_money,
        total=result.total_commission + slippage_money,
        turnover=traded_notional / starting,
    )

    # --- exposure ---------------------------------------------------------
    in_position = sum(1 for point in curve if point.position != 0)
    gross_time = Decimal(in_position) / Decimal(len(curve))
    net_ratio = sum((point.position * point.close for point in curve), _ZERO) / sum(equities, _ZERO)
    peak_concentration = max(abs(point.position * point.close) / point.equity for point in curve)
    exposure = ExposureStats(
        gross_time=gross_time,
        net_equity_ratio=net_ratio,
        peak_concentration=peak_concentration,
    )

    return RunMetrics(
        total_return=total_return,
        annualised_return=annualised_return,
        sample_years=years,
        volatility=volatility,
        drawdown=drawdown_stats,
        trades=trades,
        costs=costs,
        exposure=exposure,
        assumptions=_assumptions(),
    )
