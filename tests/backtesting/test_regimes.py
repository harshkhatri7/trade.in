"""Regime segmentation: causal labels, entry-time attribution, honesty rules.

Golden traces, hand-computed:

- Volatility on closes (100, 103, 101.97, 100.9503, 99.940797),
  window 4: returns are (+0.03, -0.01, -0.01, -0.01), mean 0,
  population variance (0.0009 + 3 * 0.0001) / 4 = 0.0003, so the
  deviation sqrt(0.0003) is about 0.01732 — above a 0.015 threshold
  and below 0.025. The first 4 bars have no trailing window and stay
  ``undefined``.
- Trend, window 1 on the same closes: +0.03 is up against a 0.02
  threshold and ranging against 0.05; -0.01 is down against a 0.005
  threshold.
- The golden run (Threshold, zero costs) opens its position at t2 and
  closes it at t4: one losing trip of exactly -12 ((99 - 105) * 2),
  attributed to whatever label carries t2.
- A dip-buy run on five hand-made bars enters at t2 open 90 and exits
  at t3 open 108: +18 realised, all of it entered under one regime,
  which is what ``regime_specific`` flags.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from harsh_quant_os.backtesting import (
    UNDEFINED,
    BacktestConfig,
    BacktestError,
    DecisionContext,
    RegimeLabels,
    RegimeSegment,
    RegimeSplit,
    run_backtest,
    split_by_regime,
    trade_records,
    trend_regimes,
    volatility_regimes,
)
from harsh_quant_os.data.providers import Bar
from tests.backtesting.test_engine import GOLDEN_BARS, ApproveAll, Threshold, _bar, _config, _data

pytestmark = pytest.mark.backtesting

# Closes 100 -> 103 -> 101.97 -> 100.9503 -> 99.940797: returns
# +0.03 then three exactly -0.01 steps (each close is 0.99x the last
# after the first bar), all exact in Decimal.
_RATIO_BARS = (
    _bar(0, "100", "100"),
    _bar(1, "103", "103"),
    _bar(2, "101.97", "101.97"),
    _bar(3, "100.9503", "100.9503"),
    _bar(4, "99.940797", "99.940797"),
)


class DipRip:
    """Buy close <= 95, exit close > 105 — one winning trip on its bars."""

    name = "dip-rip"

    def decide(self, context: DecisionContext) -> Decimal | None:
        if context.bar.close <= 95:
            return Decimal(1)
        if context.bar.close > 105:
            return Decimal(0)
        return None

    def describe(self) -> Mapping[str, str]:
        return {"rule": "close <= 95 -> 1, close > 105 -> 0, else hold"}


class EnterNeverExit:
    """Buy close <= 95 and stay — the run ends holding the position."""

    name = "enter-never-exit"

    def decide(self, context: DecisionContext) -> Decimal | None:
        return Decimal(1) if context.bar.close <= 95 else None

    def describe(self) -> Mapping[str, str]:
        return {"rule": "close <= 95 -> 1, else hold"}


def _dip_bars() -> tuple[Bar, ...]:
    """Five bars: dip to 90, rip to 110, exit at the next open 108."""
    return (
        _bar(0, "100", "100"),
        _bar(1, "100", "90"),
        _bar(2, "90", "110"),
        _bar(3, "108", "105"),
        _bar(4, "105", "106"),
    )


def _open_bars() -> tuple[Bar, ...]:
    """Three bars: the entry fills at t2 and nothing ever closes it."""
    return (
        _bar(0, "100", "100"),
        _bar(1, "100", "90"),
        _bar(2, "90", "95"),
    )


def _zero_costs() -> BacktestConfig:
    return _config(commission_bps="0", slippage_bps="0")


# ---------------------------------------------------------------------------
# Causal labelling
# ---------------------------------------------------------------------------


def test_volatility_labels_are_hand_computable_and_causal() -> None:
    data = _data(_RATIO_BARS)

    hot = volatility_regimes(data, window=4, threshold=Decimal("0.015"))
    cold = volatility_regimes(data, window=4, threshold=Decimal("0.025"))

    assert hot.labels == (UNDEFINED, UNDEFINED, UNDEFINED, UNDEFINED, "high_vol")
    assert cold.labels == (UNDEFINED, UNDEFINED, UNDEFINED, UNDEFINED, "low_vol")
    assert "trailing 4-bar population stdev" in hot.rule
    assert "0.015" in hot.rule
    assert "first 4 bars are undefined" in cold.rule


def test_trend_labels_up_down_ranging_and_warmup() -> None:
    data = _data(_RATIO_BARS)

    strict = trend_regimes(
        data, window=1, up_threshold=Decimal("0.02"), down_threshold=Decimal("0.005")
    )
    wide = trend_regimes(
        data, window=1, up_threshold=Decimal("0.05"), down_threshold=Decimal("0.05")
    )

    assert strict.labels == (UNDEFINED, "up", "down", "down", "down")
    assert wide.labels == (UNDEFINED, "ranging", "ranging", "ranging", "ranging")
    assert "trailing 1 bar(s) > 0.02 -> up" in strict.rule
    assert "< -0.005 -> down" in strict.rule


def test_a_window_that_cannot_fit_the_data_is_refused() -> None:
    data = _data(_RATIO_BARS)

    with pytest.raises(BacktestError, match="cannot fit"):
        volatility_regimes(data, window=5, threshold=Decimal("0.01"))
    with pytest.raises(BacktestError, match="cannot fit"):
        trend_regimes(data, window=5, up_threshold=Decimal("0.01"), down_threshold=Decimal("0.01"))


def test_window_and_threshold_refusals() -> None:
    data = _data(_RATIO_BARS)

    with pytest.raises(BacktestError, match="at least 2"):
        volatility_regimes(data, window=1, threshold=Decimal("0.01"))
    with pytest.raises(BacktestError, match="dispersion"):
        volatility_regimes(data, window=4, threshold=Decimal("-0.01"))
    with pytest.raises(BacktestError, match="must be a Decimal"):
        volatility_regimes(data, window=4, threshold=0.015)  # type: ignore[arg-type]
    with pytest.raises(BacktestError, match="must be finite"):
        volatility_regimes(data, window=4, threshold=Decimal("NaN"))
    with pytest.raises(BacktestError, match="at least 1"):
        trend_regimes(data, window=0, up_threshold=Decimal("0.01"), down_threshold=Decimal("0.01"))
    with pytest.raises(BacktestError, match="is a magnitude"):
        trend_regimes(data, window=1, up_threshold=Decimal("-0.01"), down_threshold=Decimal("0.01"))
    with pytest.raises(BacktestError, match="is a magnitude"):
        trend_regimes(data, window=1, up_threshold=Decimal("0.01"), down_threshold=Decimal("-0.01"))


def test_regime_labels_carry_the_rule_and_never_an_empty_label() -> None:
    with pytest.raises(BacktestError, match="must carry the rule"):
        RegimeLabels(rule="   ", labels=("a", "b"))
    with pytest.raises(BacktestError, match="at least one bar"):
        RegimeLabels(rule="a rule", labels=())
    with pytest.raises(BacktestError, match="must not be empty"):
        RegimeLabels(rule="a rule", labels=("a", ""))


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


def test_the_golden_trip_is_attributed_to_its_entry_regime() -> None:
    result = run_backtest(_data(), Threshold(), _zero_costs(), risk=ApproveAll())

    records = trade_records(result)
    assert len(records.completed) == 1
    trip = records.completed[0]
    assert trip.entry == GOLDEN_BARS[2].timestamp
    assert trip.exit == GOLDEN_BARS[4].timestamp
    assert trip.holding == timedelta(minutes=2)
    assert trip.pnl == Decimal("-12")
    assert records.open_entry is None

    split = split_by_regime(
        result,
        RegimeLabels(
            rule="test rule: high after t1, low after t3",
            labels=(UNDEFINED, "low_vol", "high_vol", "high_vol", "high_vol"),
        ),
    )

    assert split.rule == "test rule: high after t1, low after t3"
    assert [segment.label for segment in split.segments] == [UNDEFINED, "low_vol", "high_vol"]
    undefined, low_vol, high_vol = split.segments

    assert (undefined.bars, undefined.trades, undefined.realised) == (1, 0, Decimal(0))
    assert undefined.hit_rate is None and undefined.hit_interval is None
    assert (low_vol.bars, low_vol.trades, low_vol.realised) == (1, 0, Decimal(0))
    assert (high_vol.bars, high_vol.trades) == (3, 1)
    assert (high_vol.losses, high_vol.wins, high_vol.breakeven) == (1, 0, 0)
    assert high_vol.realised == Decimal("-12")
    assert high_vol.hit_rate == Decimal(0)
    assert high_vol.hit_interval is not None
    low_bound, high_bound = high_vol.hit_interval
    assert Decimal(0) <= low_bound <= high_bound <= Decimal(1)

    assert split.bars == 5
    assert split.completed == 1
    assert split.open_positions == 0
    assert split.realised == Decimal("-12") == result.realised_pnl
    assert split.undefined_bars == 1
    assert split.positive_regimes == 0
    assert split.regime_specific is False


def test_a_single_regime_profit_is_reported_as_regime_specific() -> None:
    result = run_backtest(_data(_dip_bars()), DipRip(), _zero_costs(), risk=ApproveAll())
    assert result.realised_pnl == Decimal(18)

    split = split_by_regime(
        result,
        RegimeLabels(
            rule="test rule: high until t2, low from t3",
            labels=("high_vol", "high_vol", "high_vol", "low_vol", "low_vol"),
        ),
    )

    high_vol, low_vol = split.segments
    assert (high_vol.trades, high_vol.wins, high_vol.realised) == (1, 1, Decimal(18))
    assert high_vol.hit_rate == Decimal(1)
    assert (low_vol.trades, low_vol.realised) == (0, Decimal(0))
    assert split.realised == Decimal(18) == result.realised_pnl
    assert split.positive_regimes == 1
    assert split.regime_specific is True


def test_the_open_position_is_counted_under_its_entry_regime() -> None:
    result = run_backtest(_data(_open_bars()), EnterNeverExit(), _zero_costs(), risk=ApproveAll())

    split = split_by_regime(
        result,
        RegimeLabels(rule="test rule", labels=(UNDEFINED, UNDEFINED, "high_vol")),
    )

    undefined, high_vol = split.segments
    assert (undefined.bars, undefined.open_at_end) == (2, 0)
    assert (high_vol.bars, high_vol.trades, high_vol.open_at_end) == (1, 0, 1)
    assert high_vol.realised == Decimal(0)
    assert split.completed == 0
    assert split.open_positions == 1
    assert split.realised == Decimal(0)


def test_labels_from_another_window_are_refused_not_zipped() -> None:
    result = run_backtest(_data(), Threshold(), _zero_costs(), risk=ApproveAll())

    with pytest.raises(BacktestError, match="another window"):
        split_by_regime(result, RegimeLabels(rule="short", labels=("a", "b", "c")))


def test_a_cycle_entry_off_the_run_s_own_curve_is_refused() -> None:
    result = run_backtest(_data(), Threshold(), _zero_costs(), risk=ApproveAll())
    order = result.orders[0]
    # Still between the decision (t1) and the exit (t4), so the ledger
    # walk keeps the cycle's shape — only the entry time moves off-grid.
    elsewhere = GOLDEN_BARS[2].timestamp.replace(second=30)
    tampered = replace(result, orders=(replace(order, fill_time=elsewhere), *result.orders[1:]))

    with pytest.raises(BacktestError, match="is not one of the run's bar times"):
        split_by_regime(
            tampered,
            RegimeLabels(rule="test rule", labels=("a", "b", "c", "c", "c")),
        )


def test_a_result_that_disagrees_with_its_ledger_is_refused() -> None:
    result = run_backtest(_data(), Threshold(), _zero_costs(), risk=ApproveAll())
    tampered = replace(result, realised_pnl=Decimal(0))

    with pytest.raises(BacktestError, match="disagree with its ledger"):
        split_by_regime(
            tampered,
            RegimeLabels(rule="test rule", labels=("a", "b", "c", "c", "c")),
        )


# ---------------------------------------------------------------------------
# A split that cannot account for itself
# ---------------------------------------------------------------------------


def _segment(
    label: str = "x",
    *,
    bars: int = 1,
    trades: int = 0,
    wins: int = 0,
    losses: int = 0,
    breakeven: int = 0,
    open_at_end: int = 0,
    realised: str = "0",
) -> RegimeSegment:
    return RegimeSegment(
        label=label,
        bars=bars,
        trades=trades,
        wins=wins,
        losses=losses,
        breakeven=breakeven,
        open_at_end=open_at_end,
        realised=Decimal(realised),
    )


def test_a_segment_that_cannot_account_for_itself_is_refused() -> None:
    with pytest.raises(BacktestError, match="breakeven != 3 trades"):
        _segment(trades=3, wins=1, losses=1)
    with pytest.raises(BacktestError, match="cannot be negative"):
        _segment(wins=-1)
    with pytest.raises(BacktestError, match="has no bars"):
        _segment(bars=0)
    with pytest.raises(BacktestError, match="finite decimal"):
        _segment(realised="NaN")


def test_a_split_that_cannot_account_for_itself_is_refused() -> None:
    with pytest.raises(BacktestError, match="at least one segment"):
        RegimeSplit(
            rule="r", segments=(), bars=1, completed=0, open_positions=0, realised=Decimal(0)
        )
    with pytest.raises(BacktestError, match="appears twice"):
        RegimeSplit(
            rule="r",
            segments=(_segment("x"), _segment("x")),
            bars=2,
            completed=0,
            open_positions=0,
            realised=Decimal(0),
        )
    with pytest.raises(BacktestError, match="cannot account for itself"):
        RegimeSplit(
            rule="r",
            segments=(_segment(),),
            bars=7,
            completed=0,
            open_positions=0,
            realised=Decimal(0),
        )
    with pytest.raises(BacktestError, match="one instrument holds one position"):
        RegimeSplit(
            rule="r",
            segments=(_segment("a", bars=2, open_at_end=1), _segment("b", bars=2, open_at_end=1)),
            bars=4,
            completed=0,
            open_positions=2,
            realised=Decimal(0),
        )
    with pytest.raises(BacktestError, match="segments sum to"):
        RegimeSplit(
            rule="r",
            segments=(_segment(),),
            bars=1,
            completed=0,
            open_positions=0,
            realised=Decimal(5),
        )
