"""Metric tests: §4's figures restated from the golden scenario by hand.

Every expected value below is worked out in the test itself from the
scenario's literals (equity 1000, 1000, 995.684895, 989.684895,
987.387994 over five one-minute bars, one round trip, two fills) —
the implementation is never the source of its own expectations. Where a
figure is a formula rather than a literal (annualisation, volatility,
Sharpe), the formula is re-implemented inline as the specification of
what must be computed, so a changed convention fails the equality.

Also pinned: undefined figures are ``None`` with a note rather than a
plausible number, assumptions are attached and sorted, and a
non-positive account is refused instead of summarised.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from harsh_quant_os.backtesting import (
    BacktestError,
    BacktestResult,
    DecisionContext,
    EquityPoint,
    compute_metrics,
    run_backtest,
)
from tests.backtesting.test_engine import (
    GOLDEN_BARS,
    ApproveAll,
    Threshold,
    _config,
    _data,
)

pytestmark = pytest.mark.backtesting

#: The golden run's equity marks (worked out in test_engine's docstring).
_EQUITIES = (
    Decimal(1000),
    Decimal(1000),
    Decimal("995.684895"),
    Decimal("989.684895"),
    Decimal("987.387994"),
)


class Never:
    """A strategy that never trades — the all-zero baseline."""

    name = "never"

    def decide(self, context: DecisionContext) -> Decimal | None:
        return None

    def describe(self) -> Mapping[str, str]:
        return {}


@pytest.fixture
def golden() -> BacktestResult:
    return run_backtest(_data(), Threshold(), _config(), risk=ApproveAll())


@pytest.fixture
def untouched() -> BacktestResult:
    return run_backtest(_data(), Never(), _config(), risk=ApproveAll())


# ---------------------------------------------------------------------------
# Returns and annualisation
# ---------------------------------------------------------------------------


def test_total_return_and_sample_years_are_exact(golden: BacktestResult) -> None:
    metrics = compute_metrics(golden)
    # 987.387994 / 1000 - 1, no rounding anywhere.
    assert metrics.total_return == Decimal("-0.012612006")
    # Four one-minute steps: 240 seconds over a 365-day year.
    assert metrics.sample_years == Decimal(240) / Decimal(31_536_000)


def test_annualised_return_follows_the_stated_convention(
    golden: BacktestResult,
) -> None:
    metrics = compute_metrics(golden)
    years = Decimal(240) / Decimal(31_536_000)
    # Restated: equity ratio annualised over actual elapsed time.
    expected = (Decimal("987.387994") / Decimal(1000)) ** (Decimal(1) / years) - 1
    assert metrics.annualised_return == expected


def test_metrics_are_derived_deterministically(golden: BacktestResult) -> None:
    assert compute_metrics(golden) == compute_metrics(golden)


# ---------------------------------------------------------------------------
# Risk statistics
# ---------------------------------------------------------------------------


def test_volatility_and_sharpe_restate_the_formula(golden: BacktestResult) -> None:
    metrics = compute_metrics(golden)

    # Population std (ddof=0) of simple per-bar returns, annualised by
    # sqrt(bar frequency) — the §4 convention, re-implemented here.
    returns = [_EQUITIES[index] / _EQUITIES[index - 1] - 1 for index in range(1, 5)]
    count = Decimal(len(returns))
    mean = sum(returns) / count
    sigma = (sum((value - mean) ** 2 for value in returns) / count).sqrt()
    years = Decimal(240) / Decimal(31_536_000)
    frequency = count / years

    assert sigma > 0
    assert metrics.volatility.annualised == sigma * frequency.sqrt()
    assert metrics.volatility.sharpe == (mean / sigma) * frequency.sqrt()
    assert metrics.volatility.note == ""


def test_drawdown_is_hand_computable(golden: BacktestResult) -> None:
    drawdown = compute_metrics(golden).drawdown
    # Deepest fall: 1000 -> 987.387994, ratio 12.612006 / 1000.
    assert drawdown.max_drawdown == Decimal("0.012612006")
    assert drawdown.max_drawdown_amount == Decimal("12.612006")
    # The running high was set at bar0 (bar1 merely matched it) and the
    # curve never returned, so the peak stands at the first bar and the
    # sample ends still under water.
    assert drawdown.peak_time == GOLDEN_BARS[0].timestamp
    assert drawdown.trough_time == GOLDEN_BARS[4].timestamp
    assert drawdown.time_under_water == timedelta(minutes=4)
    assert drawdown.recovered is False


# ---------------------------------------------------------------------------
# Trades, costs, exposure
# ---------------------------------------------------------------------------


def test_trade_statistics_count_the_one_loss_trip(golden: BacktestResult) -> None:
    trades = compute_metrics(golden).trades
    assert trades.round_trips == 1
    assert (trades.wins, trades.losses, trades.breakeven) == (0, 1, 0)
    assert trades.hit_rate == Decimal(0)  # 0 wins / (0 + 1 losses)
    assert trades.pnls == (Decimal("-12.408"),)
    # Entry at bar2's fill, flat at bar4's fill: two minutes.
    assert trades.median_holding == timedelta(minutes=2)
    # The losing side's distribution: one value, so all four are it.
    assert trades.median_loss == Decimal("-12.408")
    assert trades.mean_loss == Decimal("-12.408")
    assert trades.min_loss == Decimal("-12.408")
    assert trades.max_loss == Decimal("-12.408")
    # The winning side does not exist and must read as such.
    assert trades.median_win is None
    assert trades.mean_win is None
    assert trades.min_win is None
    assert trades.max_win is None
    assert trades.open_position_at_end is False


def test_costs_and_turnover_are_exact(golden: BacktestResult) -> None:
    costs = compute_metrics(golden).costs
    assert costs.commission == Decimal("0.204006")
    # Slippage money: (105.105 - 105) * 2 + (98.901 - 99) * -2
    #               = 0.21 + 0.198
    assert costs.slippage == Decimal("0.408")
    assert costs.total == Decimal("0.612006")
    # Gross traded notional 210.21 + 197.802 = 408.012 over 1000.
    assert costs.turnover == Decimal("0.408012")


def test_exposure_is_hand_computable(golden: BacktestResult) -> None:
    exposure = compute_metrics(golden).exposure
    # Position path across the five bars: 0, 0, 2, 2, 0.
    assert exposure.gross_time == Decimal("0.4")
    # sum(position * close) = 206 + 200 = 406
    # sum(equity) = 1000 + 1000 + 995.684895 + 989.684895 + 987.387994
    #             = 4972.757784
    assert exposure.net_equity_ratio == Decimal(406) / Decimal("4972.757784")
    # Peak concentration is bar2: 206 / 995.684895 (bar3's is smaller).
    assert exposure.peak_concentration == Decimal(206) / Decimal("995.684895")


# ---------------------------------------------------------------------------
# Assumptions and the refusal cases
# ---------------------------------------------------------------------------


def test_assumptions_are_attached_and_sorted(golden: BacktestResult) -> None:
    assumptions = compute_metrics(golden).assumptions
    keys = [key for key, _ in assumptions]
    assert keys == sorted(keys)
    by_key = dict(assumptions)
    assert by_key["risk_free_rate"] == "0 (stated, not estimated)"
    assert "ddof=0" in by_key["volatility"]
    assert "365-day" in by_key["annualisation"]
    assert "explicitly not modelled" in by_key["costs"]
    assert "not a completed trade" in by_key["trades"]
    assert len(assumptions) >= 10


def test_a_run_without_trades_reads_zero_and_none(untouched: BacktestResult) -> None:
    metrics = compute_metrics(untouched)
    assert metrics.total_return == Decimal(0)
    assert metrics.annualised_return == Decimal(0)
    # Zero dispersion is undefined, not zero — and it says so.
    assert metrics.volatility.annualised is None
    assert metrics.volatility.sharpe is None
    assert "zero dispersion" in metrics.volatility.note
    # No fall: no drawdown record at all.
    assert metrics.drawdown.max_drawdown == Decimal(0)
    assert metrics.drawdown.peak_time is None
    assert metrics.drawdown.trough_time is None
    assert metrics.drawdown.time_under_water is None
    assert metrics.drawdown.recovered is True
    assert metrics.trades.round_trips == 0
    assert metrics.trades.hit_rate is None
    assert metrics.trades.median_holding is None
    assert metrics.trades.pnls == ()
    assert metrics.costs.total == Decimal(0)
    assert metrics.costs.turnover == Decimal(0)
    assert metrics.exposure.gross_time == Decimal(0)
    assert metrics.exposure.net_equity_ratio == Decimal(0)
    assert metrics.exposure.peak_concentration == Decimal(0)


def test_non_positive_equity_is_refused_not_summarised(
    golden: BacktestResult,
) -> None:
    broken = replace(
        golden,
        equity_curve=(
            EquityPoint(
                time=GOLDEN_BARS[0].timestamp,
                equity=Decimal(0),
                position=Decimal(0),
                close=Decimal(100),
            ),
            EquityPoint(
                time=GOLDEN_BARS[1].timestamp,
                equity=Decimal("-5"),
                position=Decimal(0),
                close=Decimal(100),
            ),
        ),
    )
    with pytest.raises(BacktestError, match="non-positive"):
        compute_metrics(broken)


def test_a_single_equity_point_is_not_a_sample(golden: BacktestResult) -> None:
    truncated = replace(golden, equity_curve=(golden.equity_curve[0],))
    with pytest.raises(BacktestError, match="at least two equity points"):
        compute_metrics(truncated)
