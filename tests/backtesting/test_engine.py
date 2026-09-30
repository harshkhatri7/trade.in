"""Engine-core tests with hand-computed golden values (Phase 6, increment 1).

Every expectation below is arithmetic done by hand in Decimal and
written out where it is asserted; nothing here was produced by running
the system under test. The scenario:

Bars (XBTUSD, 1m, UTC): opens/closes 100/100, 102/104, 105/103,
101/100, 99/98. A threshold strategy targets position 2 when the close
is above 100 and 0 otherwise. Slippage 10 bps (buys above the open,
sells below it), commission 5 bps of absolute notional.

Trace:

- bar0 close 100 → target 0 = position → no order.
- bar1 close 104 → target 2, delta +2 → queued.
- bar2 open 105 → fill 105 * 1.001 = **105.105**; fee 210.21 *
  0.0005 = **0.105105**; cash 1000 - 210.21 - 0.105105 =
  **789.684895**; mark close 103 → equity **995.684895**.
- bar3 close 100 → target 0 ≠ position 2 → delta -2 → queued.
- bar4 open 99 → fill 99 * 0.999 = **98.901**; fee 197.802 *
  0.0005 = **0.098901**; cash 789.684895 + 197.802 - 0.098901 =
  **987.387994**; realised (98.901 - 105.105) * 2 = **-12.408**;
  commissions **0.204006**; flat at close 98 → equity
  **987.387994**.

Identity: 1000 + (-12.408) - 0.204006 + 0 = 987.387994. ✓
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from harsh_quant_os.backtesting import (
    BacktestConfig,
    BacktestData,
    BacktestError,
    BpsCommission,
    CausalityViolation,
    CommissionModel,
    DecisionContext,
    FixedBpsSlippage,
    HistoryView,
    Ledger,
    OrderStatus,
    SlippageModel,
    run_backtest,
    window_coverage,
)
from harsh_quant_os.backtesting.data import load_backtest_data
from harsh_quant_os.config import Settings
from harsh_quant_os.data.providers import Bar
from harsh_quant_os.quant.recipes.recipe import RecipeError
from harsh_quant_os.safety import ConfiguredRiskEvaluator
from harsh_quant_os.safety.risk import RiskEvaluation, RiskEvaluator
from tests.quant.test_recipes import GOOD_ROWS, _csv_bytes, _write_store

pytestmark = pytest.mark.backtesting

# ---------------------------------------------------------------------------
# Fixtures: bars, strategies, config, risk doubles
# ---------------------------------------------------------------------------

_VERSION = "a" * 64


def _bar(
    minute: int,
    open_: str,
    close: str,
    *,
    symbol: str = "XBTUSD",
    timeframe: str = "1m",
) -> Bar:
    """One internally consistent bar (high/low derived from open/close)."""
    opening = Decimal(open_)
    closing = Decimal(close)
    return Bar(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=datetime(2024, 1, 1, 0, minute, tzinfo=UTC),
        open=opening,
        high=max(opening, closing) + 1,
        low=min(opening, closing) - 1,
        close=closing,
        volume=Decimal(10),
    )


def _bar_at(second: int, *, timeframe: str = "1m") -> Bar:
    """One bar ``second`` seconds after midnight — sub-minute grids."""
    stamp = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(seconds=second)
    return Bar(
        symbol="XBTUSD",
        timeframe=timeframe,
        timestamp=stamp,
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal(100),
        volume=Decimal(10),
    )


GOLDEN_BARS = (
    _bar(0, "100", "100"),
    _bar(1, "102", "104"),
    _bar(2, "105", "103"),
    _bar(3, "101", "100"),
    _bar(4, "99", "98"),
)


class Threshold:
    """Target 2 while the close is above 100, else flat.

    Records (bar time, position) as seen, so tests can pin the
    sequencing: the recording never influences the decision.
    """

    name = "threshold"

    def __init__(self) -> None:
        self.calls: list[tuple[datetime, Decimal]] = []

    def decide(self, context: DecisionContext) -> Decimal | None:
        self.calls.append((context.bar.timestamp, context.position))
        return Decimal(2) if context.bar.close > 100 else Decimal(0)

    def describe(self) -> Mapping[str, str]:
        return {"target_qty": "2", "entry": "close > 100"}


class Parity:
    """Target 1 on even-length histories, flat on odd — exercises expiry."""

    name = "parity"

    def decide(self, context: DecisionContext) -> Decimal | None:
        return Decimal(1) if len(context.history) % 2 == 0 else Decimal(0)

    def describe(self) -> Mapping[str, str]:
        return {"rule": "len(history) % 2 == 0"}


class PeekFuture:
    """Tries to read one past the current bar — must be impossible."""

    name = "peek"

    def decide(self, context: DecisionContext) -> Decimal | None:
        _ = context.history[len(context.history)]  # IndexError is the point
        return None

    def describe(self) -> Mapping[str, str]:
        return {}


class ApproveAll:
    """Risk double: approves everything, counts invocations (spy)."""

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(
        self,
        *,
        decision_time: datetime,
        position: Decimal,
        delta: Decimal,
        price: Decimal,
        equity: Decimal,
    ) -> RiskEvaluation:
        self.calls += 1
        return RiskEvaluation.allow()


class RefuseSells:
    """Risk double: refuses any order that reduces a long position."""

    def evaluate(
        self,
        *,
        decision_time: datetime,
        position: Decimal,
        delta: Decimal,
        price: Decimal,
        equity: Decimal,
    ) -> RiskEvaluation:
        if delta < 0:
            return RiskEvaluation.refuse("sell side disabled by test configuration")
        return RiskEvaluation.allow()


def _config(*, slippage_bps: str = "10", commission_bps: str = "5") -> BacktestConfig:
    """The golden run's explicit inputs (zeros only when asked for)."""
    return BacktestConfig(
        starting_capital=Decimal(1000),
        commission=BpsCommission(rate_bps=Decimal(commission_bps)),
        slippage=FixedBpsSlippage(bps=Decimal(slippage_bps)),
    )


def _data(bars: Sequence[Bar] = GOLDEN_BARS) -> BacktestData:
    return BacktestData(dataset_id="test.bars", version=_VERSION, bars=tuple(bars))


# ---------------------------------------------------------------------------
# The golden money path
# ---------------------------------------------------------------------------


def test_golden_hand_computed_money_path() -> None:
    result = run_backtest(_data(), Threshold(), _config(), risk=ApproveAll())

    assert len(result.orders) == 2
    first, second = result.orders

    assert first.status is OrderStatus.FILLED
    assert first.decision_time == GOLDEN_BARS[1].timestamp
    assert first.delta == Decimal(2)
    assert first.fill_time == GOLDEN_BARS[2].timestamp
    assert first.fill_price == Decimal("105.105")  # 105 * 1.001
    assert first.reference_open == Decimal(105)
    assert first.commission == Decimal("0.105105")  # 210.21 * 0.0005

    assert second.status is OrderStatus.FILLED
    assert second.decision_time == GOLDEN_BARS[3].timestamp
    assert second.delta == Decimal(-2)
    assert second.fill_time == GOLDEN_BARS[4].timestamp
    assert second.fill_price == Decimal("98.901")  # 99 * 0.999
    assert second.reference_open == Decimal(99)
    assert second.commission == Decimal("0.098901")  # 197.802 * 0.0005

    assert result.ending_cash == Decimal("987.387994")
    assert result.ending_quantity == Decimal(0)
    assert result.ending_equity == Decimal("987.387994")
    assert result.ending_unrealised == Decimal(0)
    assert result.realised_pnl == Decimal("-12.408")  # (98.901 - 105.105) * 2
    assert result.total_commission == Decimal("0.204006")

    # Closing identity, exact here (no average-cost division occurred).
    assert (
        result.starting_capital
        + result.realised_pnl
        - result.total_commission
        + result.ending_unrealised
    ) == result.ending_equity


def test_equity_curve_marks_every_bar_close_in_time_order() -> None:
    result = run_backtest(_data(), Threshold(), _config(), risk=ApproveAll())

    assert [point.time for point in result.equity_curve] == [bar.timestamp for bar in GOLDEN_BARS]
    assert [point.equity for point in result.equity_curve] == [
        Decimal(1000),  # flat
        Decimal(1000),  # flat at bar1 close
        Decimal("995.684895"),  # 789.684895 + 2 * 103
        Decimal("989.684895"),  # + 2 * 100
        Decimal("987.387994"),  # flat after the closing sell
    ]


def test_sequencing_fill_then_mark_then_decide() -> None:
    strategy = Threshold()
    run_backtest(_data(), strategy, _config(), risk=ApproveAll())

    # One decision per bar, and each sees the position *after* that
    # bar's opening fill: 2 arrives at bar2's decision, leaves at bar4's.
    assert strategy.calls == [
        (GOLDEN_BARS[0].timestamp, Decimal(0)),
        (GOLDEN_BARS[1].timestamp, Decimal(0)),
        (GOLDEN_BARS[2].timestamp, Decimal(2)),
        (GOLDEN_BARS[3].timestamp, Decimal(2)),
        (GOLDEN_BARS[4].timestamp, Decimal(0)),
    ]


def test_result_records_provenance_and_sorted_parameters() -> None:
    result = run_backtest(_data(), Threshold(), _config(), risk=ApproveAll())

    assert result.dataset_id == "test.bars"
    assert result.dataset_version == _VERSION
    assert result.strategy_name == "threshold"
    assert result.strategy_parameters == (
        ("entry", "close > 100"),
        ("target_qty", "2"),
    )  # sorted by key, not by the strategy's construction order
    assert result.intrabar_rule == "next_bar_open"


def test_runs_are_bit_identical() -> None:
    first = run_backtest(_data(), Threshold(), _config(), risk=ApproveAll())
    second = run_backtest(_data(), Threshold(), _config(), risk=ApproveAll())
    assert first == second  # exact Decimal equality, field by field


# ---------------------------------------------------------------------------
# The intrabar rule and the final-bar expiry
# ---------------------------------------------------------------------------


def test_order_decided_on_the_final_bar_expires_uneilled() -> None:
    bars = (_bar(0, "100", "99"), _bar(1, "100", "100"), _bar(2, "101", "102"))
    # parity: bar0 (len 1) → 0 = position (no order); bar1 (len 2) → 1
    # queued and filled at bar2's open 101; bar2 (len 3) → 0, but it is
    # the final bar: the sell cannot fill and must say so.
    result = run_backtest(
        _data(bars),
        Parity(),
        _config(slippage_bps="0", commission_bps="0"),
        risk=ApproveAll(),
    )

    filled, expired = result.orders
    assert filled.status is OrderStatus.FILLED
    assert filled.decision_time == bars[1].timestamp
    assert filled.fill_time == bars[2].timestamp
    assert filled.fill_price == Decimal(101)  # explicit zero slippage

    assert expired.status is OrderStatus.EXPIRED
    assert expired.decision_time == bars[2].timestamp
    assert expired.delta == Decimal(-1)
    assert expired.fill_time is None
    assert expired.fill_price is None
    assert "final bar" in expired.note

    # The position survives: 1000 - 101 = 899 cash, 1 unit marked at 102.
    assert result.ending_quantity == Decimal(1)
    assert result.ending_cash == Decimal(899)
    assert result.ending_equity == Decimal(1001)  # 899 + 102
    assert result.ending_unrealised == Decimal(1)  # 102 - 101


def test_an_order_never_fills_at_or_before_its_own_decision() -> None:
    result = run_backtest(_data(), Threshold(), _config(), risk=ApproveAll())
    for order in result.filled:
        assert order.fill_time is not None
        assert order.fill_time > order.decision_time
        assert order.fill_time.tzinfo is not None  # timezone-aware compare


def test_causality_violation_is_raised_not_logged() -> None:
    # Bypass construction-time validation on purpose: the data layer
    # refuses non-increasing stamps (tested below), and this reaches
    # the engine's own second-layer assertion behind it.
    descending = (_bar(5, "100", "101"), _bar(0, "100", "99"))
    broken = BacktestData.__new__(BacktestData)
    object.__setattr__(broken, "dataset_id", "broken.bars")
    object.__setattr__(broken, "version", _VERSION)
    object.__setattr__(broken, "bars", descending)

    class AlwaysOne:
        name = "always-one"

        def decide(self, context: DecisionContext) -> Decimal | None:
            return Decimal(1)

        def describe(self) -> Mapping[str, str]:
            return {}

    with pytest.raises(CausalityViolation, match="may only fill after"):
        run_backtest(
            broken,
            AlwaysOne(),
            _config(),
            risk=ApproveAll(),
        )


# ---------------------------------------------------------------------------
# Bounded history: the future is not addressable
# ---------------------------------------------------------------------------


def test_history_rejects_reaching_past_the_current_bar() -> None:
    # The first decision is at bar0, where the view holds exactly 1 bar
    # and index 1 is already the future.
    with pytest.raises(IndexError, match="bounded at 1 bar"):
        run_backtest(_data(), PeekFuture(), _config(), risk=ApproveAll())


def test_history_view_unit_contract() -> None:
    view = HistoryView(GOLDEN_BARS, 2)
    assert len(view) == 2
    assert view[0] is GOLDEN_BARS[0]
    assert view[-1] is GOLDEN_BARS[1]  # the view's own tail, not the data's
    assert view[:99] == (GOLDEN_BARS[0], GOLDEN_BARS[1])  # slicing clamps
    assert [bar.close for bar in view] == [Decimal(100), Decimal(104)]

    with pytest.raises(IndexError, match="bounded at 2 bars"):
        _ = view[2]  # the current bar exists in the data — not here
    with pytest.raises(IndexError, match="bounded at 2 bars"):
        _ = view[-3]  # negative out-of-range too
    with pytest.raises(IndexError, match="do not exist"):
        _ = HistoryView(GOLDEN_BARS, 99)  # bound beyond the data is refused


def test_appending_future_bars_changes_no_earlier_decision() -> None:
    short = _data(GOLDEN_BARS[:4])
    full = _data(GOLDEN_BARS)
    result_short = run_backtest(short, Threshold(), _config(), risk=ApproveAll())
    result_full = run_backtest(full, Threshold(), _config(), risk=ApproveAll())

    # Compare everything strictly before the short run's final bar: the
    # short run can only differ there (its bar3 is a last bar, whose
    # decision expires instead of filling at bar4).
    cutoff = GOLDEN_BARS[3].timestamp
    assert [o for o in result_short.orders if o.decision_time < cutoff] == [
        o for o in result_full.orders if o.decision_time < cutoff
    ]
    assert [p for p in result_short.equity_curve if p.time < cutoff] == [
        p for p in result_full.equity_curve if p.time < cutoff
    ]


# ---------------------------------------------------------------------------
# Risk evaluation in the simulated path (exit criterion 6)
# ---------------------------------------------------------------------------


def test_risk_is_consulted_for_every_non_zero_delta_order() -> None:
    risk = ApproveAll()
    run_backtest(_data(), Threshold(), _config(), risk=risk)
    # Two orders were attempted (bar1 +2, bar3 -2); the zero-delta
    # decisions never reach it.
    assert risk.calls == 2


def test_a_risk_refusal_records_a_rejection_and_never_fills() -> None:
    result = run_backtest(_data(), Threshold(), _config(), risk=RefuseSells())

    # The close at bar3 queues a sell that risk refuses; the final bar
    # queues another sell that cannot fill at all (no later bar) — the
    # structural expiry is what it is recorded as, since even an
    # approval could not have executed it.
    assert [order.status for order in result.orders] == [
        OrderStatus.FILLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    ]
    rejected = result.orders[1]
    assert rejected.delta == Decimal(-2)
    assert rejected.fill_time is None
    assert rejected.note == "sell side disabled by test configuration"
    assert "final bar" in result.orders[2].note
    assert len(result.filled) == 1
    assert len(result.rejected) == 1
    # The long position was never closed, and the equity says so.
    assert result.ending_quantity == Decimal(2)
    assert result.ending_unrealised == (Decimal("98") - Decimal("105.105")) * 2


def test_risk_evaluation_refuses_an_empty_reason() -> None:
    with pytest.raises(ValueError, match="must state its reason"):
        RiskEvaluation.refuse("   ")


def test_the_risk_protocol_is_satisfied_by_the_engine_itself() -> None:
    # Structural check: the doubles above are only doubles because the
    # contract is a Protocol — the engine depends on the shape, not a
    # concrete class (risk-engine.md §1's seam).
    assert isinstance(ApproveAll(), RiskEvaluator)


def test_configured_risk_evaluator_approves_small_orders_end_to_end() -> None:
    # The real evaluator over the real Settings defaults: the golden
    # run's largest resulting notional is ~210 against a 100k limit.
    risk = ConfiguredRiskEvaluator(Settings.load(_env_file=None))
    result = run_backtest(_data(), Threshold(), _config(), risk=risk)
    assert len(result.filled) == 2
    assert result.rejected == ()


def test_a_tight_position_limit_refuses_the_entry_in_the_engine() -> None:
    risk = ConfiguredRiskEvaluator(Settings.load(_env_file=None, risk_max_position_notional=100.0))
    result = run_backtest(_data(), Threshold(), _config(), risk=risk)

    # Bar1 (close 104) and bar2 (close 103) both attempt the entry
    # while still flat — 2 * ~104 = ~208 > 100 refuses both, each with
    # its own record. Bar3's target-0 equals the still-flat position,
    # a zero delta that never reaches risk. Nothing traded, and the
    # notes say why.
    assert [order.status for order in result.orders] == [
        OrderStatus.REJECTED,
        OrderStatus.REJECTED,
    ]
    assert all("RISK_MAX_POSITION_NOTIONAL" in order.note for order in result.orders)
    assert result.ending_quantity == Decimal(0)
    assert result.ending_cash == Decimal(1000)
    assert result.ending_equity == Decimal(1000)


# ---------------------------------------------------------------------------
# Configuration and strategy contract refusals
# ---------------------------------------------------------------------------


def test_config_refuses_implicit_or_inexact_inputs() -> None:
    with pytest.raises(BacktestError, match="must be a Decimal"):
        BacktestConfig(
            starting_capital=1000.0,  # type: ignore[arg-type]
            commission=BpsCommission(rate_bps=Decimal(0)),
            slippage=FixedBpsSlippage(bps=Decimal(0)),
        )
    with pytest.raises(BacktestError, match="must be positive"):
        BacktestConfig(
            starting_capital=Decimal(0),
            commission=BpsCommission(rate_bps=Decimal(0)),
            slippage=FixedBpsSlippage(bps=Decimal(0)),
        )
    with pytest.raises(BacktestError, match="explicit model"):
        BacktestConfig(
            starting_capital=Decimal(1000),
            commission=cast(CommissionModel, None),
            slippage=FixedBpsSlippage(bps=Decimal(0)),
        )
    with pytest.raises(BacktestError, match="explicit named model"):
        BacktestConfig(
            starting_capital=Decimal(1000),
            commission=BpsCommission(rate_bps=Decimal(0)),
            slippage=cast(SlippageModel, None),
        )


def test_strategy_return_contract_is_enforced_by_the_engine() -> None:
    class FloatTarget:
        name = "float-target"

        def decide(self, context: DecisionContext) -> Decimal | None:
            return cast(Decimal, 1.5)  # a float pretending: refused at runtime

        def describe(self) -> Mapping[str, str]:
            return {}

    with pytest.raises(BacktestError, match="must be Decimal, int or None"):
        run_backtest(_data(), FloatTarget(), _config(), risk=ApproveAll())

    class StringDescribe:
        name = "string-describe"

        def decide(self, context: DecisionContext) -> Decimal | None:
            return None

        def describe(self) -> Mapping[str, str]:
            return cast(Mapping[str, str], {"qty": 2})

    with pytest.raises(BacktestError, match="manifests are canonical JSON"):
        run_backtest(_data(), StringDescribe(), _config(), risk=ApproveAll())

    class NoName:
        name = "   "

        def decide(self, context: DecisionContext) -> Decimal | None:
            return None

        def describe(self) -> Mapping[str, str]:
            return {}

    with pytest.raises(BacktestError, match="name must be a non-empty string"):
        run_backtest(_data(), NoName(), _config(), risk=ApproveAll())


def test_two_bars_minimum() -> None:
    with pytest.raises(BacktestError, match="at least two bars"):
        run_backtest(_data((_bar(0, "100", "101"),)), Threshold(), _config(), risk=ApproveAll())


# ---------------------------------------------------------------------------
# Data boundary: validation and exact decimals from the store
# ---------------------------------------------------------------------------


def test_data_refuses_structurally_invalid_inputs() -> None:
    with pytest.raises(BacktestError, match="at least one bar"):
        _data(())
    with pytest.raises(BacktestError, match="64-character lowercase SHA-256"):
        BacktestData(dataset_id="x", version="nothex", bars=GOLDEN_BARS)
    with pytest.raises(BacktestError, match="must not be empty"):
        BacktestData(dataset_id="  ", version=_VERSION, bars=GOLDEN_BARS)
    with pytest.raises(BacktestError, match="one instrument"):
        _data(
            (
                _bar(0, "100", "101"),
                _bar(1, "3000", "3100", symbol="ETHUSD"),
            )
        )
    with pytest.raises(BacktestError, match="one timeframe"):
        _data((_bar(0, "100", "101"), _bar(1, "100", "101", timeframe="1h")))
    with pytest.raises(BacktestError, match="must strictly increase"):
        _data((_bar(1, "100", "101"), _bar(1, "101", "102")))  # same stamp


def test_load_backtest_data_keeps_exact_decimals_from_the_store(
    tmp_path: Path,
) -> None:
    payload = _csv_bytes(GOOD_ROWS)
    _write_store(tmp_path, "kraken.xbtusd.1m", payload)

    data = load_backtest_data(tmp_path, "kraken.xbtusd.1m")

    assert data.dataset_id == "kraken.xbtusd.1m"
    assert data.version == hashlib.sha256(payload).hexdigest()  # recomputed pin
    assert len(data.bars) == 3
    assert data.bars[0].close == Decimal("105")  # exact, not 104.99999
    assert data.bars[2].open == Decimal("110")
    assert data.timeframe == "1m"
    assert data.bars[0].timestamp.tzinfo is not None


def test_load_backtest_data_shares_the_store_refusals(tmp_path: Path) -> None:
    missing_volume = (
        "XBTUSD,1m,2024-01-01T00:00:00+00:00,100,110,90,105,",
        GOOD_ROWS[1],
        GOOD_ROWS[2],
    )
    _write_store(tmp_path, "kraken.xbtusd.1m", _csv_bytes(missing_volume))
    with pytest.raises(RecipeError, match="have no volume"):
        load_backtest_data(tmp_path, "kraken.xbtusd.1m")

    with pytest.raises(RecipeError, match="no stored dataset"):
        load_backtest_data(tmp_path, "does.not.exist")


# ---------------------------------------------------------------------------
# Window coverage: gaps counted, never interpolated (methodology §5)
# ---------------------------------------------------------------------------


def test_window_coverage_of_a_contiguous_window_is_complete() -> None:
    coverage = window_coverage(_data())

    assert coverage.timeframe == "1m"
    assert coverage.nominal_seconds == 60
    assert coverage.actual_bars == 5
    assert coverage.expected_bars == 5  # four minutes of span, both ends counted
    assert coverage.gap_intervals == 0
    assert coverage.missing_bars == 0
    assert coverage.irregular_intervals == 0
    assert coverage.is_complete is True


def test_window_coverage_counts_missing_bars_across_gaps() -> None:
    # Minutes 0, 2, 3, 5: two one-bar holes (minutes 1 and 4).
    data = _data(
        (_bar(0, "100", "101"), _bar(2, "100", "101"), _bar(3, "100", "101"), _bar(5, "100", "101"))
    )

    coverage = window_coverage(data)

    assert coverage.actual_bars == 4
    assert coverage.expected_bars == 6  # five minutes of span
    assert coverage.gap_intervals == 2
    assert coverage.missing_bars == 2
    assert coverage.irregular_intervals == 0  # both gaps divide evenly
    assert coverage.is_complete is False


def test_window_coverage_flags_dense_and_off_grid_intervals() -> None:
    dense = _data((_bar_at(0), _bar_at(45)))
    coverage = window_coverage(dense)
    # Denser than one bar: the record reports actual above expected
    # rather than pretending the grid held.
    assert coverage.actual_bars == 2
    assert coverage.expected_bars == 1
    assert coverage.gap_intervals == 0
    assert coverage.missing_bars == 0
    assert coverage.irregular_intervals == 1

    # 150 seconds between 1m bars: one whole bar missing plus a 30s
    # remainder that does not divide the grid.
    off_grid = _data((_bar_at(0), _bar_at(150)))
    coverage = window_coverage(off_grid)
    assert coverage.gap_intervals == 1
    assert coverage.missing_bars == 1
    assert coverage.irregular_intervals == 1
    assert coverage.is_complete is False


def test_window_coverage_states_when_it_cannot_compute() -> None:
    # Months have no fixed length; guessing 30 days would fabricate
    # the gap count, so every computable field says so instead.
    monthly = _data(
        (_bar(0, "100", "101", timeframe="1mo"), _bar(59, "100", "101", timeframe="1mo"))
    )

    coverage = window_coverage(monthly)

    assert coverage.timeframe == "1mo"
    assert coverage.nominal_seconds is None
    assert coverage.expected_bars is None
    assert coverage.gap_intervals is None
    assert coverage.missing_bars is None
    assert coverage.irregular_intervals is None
    assert coverage.actual_bars == 2
    # Unknown coverage must never read as full coverage.
    assert coverage.is_complete is False


# ---------------------------------------------------------------------------
# Ledger: the average-cost money math, hand-computed
# ---------------------------------------------------------------------------


def test_ledger_long_roundtrip_realises_then_reverses() -> None:
    ledger = Ledger(Decimal(1000))
    ledger.apply_fill(Decimal(100), Decimal(2), Decimal(0))  # buy 2
    assert ledger.quantity == Decimal(2)
    assert ledger.average_price == Decimal(100)
    assert ledger.cash == Decimal(800)

    ledger.apply_fill(Decimal(110), Decimal(-1), Decimal(0))  # sell 1 above avg
    assert ledger.realised_pnl == Decimal(10)  # (110 - 100) * 1
    ledger.apply_fill(Decimal(90), Decimal(-1), Decimal(0))  # sell 1 below avg
    assert ledger.realised_pnl == Decimal(0)  # +10 - 10
    assert ledger.quantity == Decimal(0)
    assert ledger.average_price == Decimal(0)
    assert ledger.cash == Decimal(1000)  # flat, fees were zero
    assert ledger.unrealised_pnl(Decimal(500)) == Decimal(0)


def test_ledger_short_profit_is_positive_below_the_average() -> None:
    ledger = Ledger(Decimal(1000))
    ledger.apply_fill(Decimal(100), Decimal(-2), Decimal(0))  # sell short 2
    assert ledger.cash == Decimal(1200)
    assert ledger.quantity == Decimal(-2)

    ledger.apply_fill(Decimal(90), Decimal(1), Decimal(0))  # partial cover
    assert ledger.realised_pnl == Decimal(10)  # (90 - 100) * (-1)
    ledger.apply_fill(Decimal(80), Decimal(1), Decimal(0))  # flat
    assert ledger.realised_pnl == Decimal(30)  # +10 + 20
    assert ledger.cash == Decimal(1030)  # 1000 + 30, no fees
    assert ledger.quantity == Decimal(0)


def test_ledger_crossing_through_flat_realises_then_reopens() -> None:
    ledger = Ledger(Decimal(1000))
    ledger.apply_fill(Decimal(100), Decimal(2), Decimal(0))  # long 2
    ledger.apply_fill(Decimal(110), Decimal(-5), Decimal(0))  # sell 5: flip

    assert ledger.realised_pnl == Decimal(20)  # (110 - 100) * 2 closed
    assert ledger.quantity == Decimal(-3)  # 3 short, opened at 110
    assert ledger.average_price == Decimal(110)
    assert ledger.cash == Decimal(1350)  # 800 + 550
    # equity at mark 110: 1350 - 3 * 110 = 1020 = 1000 + 20 realised.
    assert ledger.mark_equity(Decimal(110)) == Decimal(1020)
    assert ledger.unrealised_pnl(Decimal(110)) == Decimal(0)


def test_ledger_refuses_inexact_or_impossible_values_before_mutating() -> None:
    ledger = Ledger(Decimal(1000))
    with pytest.raises(BacktestError, match="must be a Decimal"):
        ledger.apply_fill(100.0, Decimal(1), Decimal(0))  # type: ignore[arg-type]
    with pytest.raises(BacktestError, match="non-zero"):
        ledger.apply_fill(Decimal(100), Decimal(0), Decimal(0))
    with pytest.raises(BacktestError, match="must be positive"):
        ledger.apply_fill(Decimal(0), Decimal(1), Decimal(0))
    with pytest.raises(BacktestError, match=">= 0"):
        ledger.apply_fill(Decimal(100), Decimal(1), Decimal(-1))
    assert ledger.cash == Decimal(1000) and ledger.quantity == Decimal(0)

    with pytest.raises(BacktestError, match="must be positive"):
        Ledger(Decimal(0))
    with pytest.raises(BacktestError, match="must be a Decimal"):
        Ledger(1000.0)  # type: ignore[arg-type]
    with pytest.raises(BacktestError, match="must be positive"):
        ledger.mark_equity(Decimal(0))


# ---------------------------------------------------------------------------
# Cost models: explicit parameters, pessimistic direction
# ---------------------------------------------------------------------------


def test_commission_is_basis_points_of_absolute_notional() -> None:
    model = BpsCommission(rate_bps=Decimal(5))
    assert model.apply(Decimal("210.21")) == Decimal("0.105105")
    assert model.apply(Decimal("-197.802")) == Decimal("0.098901")  # shorts pay
    flat = BpsCommission(rate_bps=Decimal(0), fixed_fee=Decimal("0.25"))
    assert flat.apply(Decimal(1)) == Decimal("0.25")


def test_commission_refusals() -> None:
    with pytest.raises(BacktestError, match="must be a Decimal"):
        BpsCommission(rate_bps=5.0)  # type: ignore[arg-type]
    with pytest.raises(BacktestError, match="rate_bps must be >= 0"):
        BpsCommission(rate_bps=Decimal(-1))
    with pytest.raises(BacktestError, match="fixed_fee must be >= 0"):
        BpsCommission(rate_bps=Decimal(0), fixed_fee=Decimal("-1"))


def test_slippage_is_pessimistic_in_both_directions() -> None:
    model = FixedBpsSlippage(bps=Decimal(10))
    assert model.apply(Decimal(100), buy=True) == Decimal("100.10")
    assert model.apply(Decimal(100), buy=False) == Decimal("99.90")


def test_slippage_refusals() -> None:
    with pytest.raises(BacktestError, match="bps must be >= 0"):
        FixedBpsSlippage(bps=Decimal(-1))
    with pytest.raises(BacktestError, match="below 10000"):
        FixedBpsSlippage(bps=Decimal(10_000))
    with pytest.raises(BacktestError, match="must be a Decimal"):
        FixedBpsSlippage(bps=0.1)  # type: ignore[arg-type]
    model = FixedBpsSlippage(bps=Decimal(0))
    with pytest.raises(BacktestError, match="must be positive"):
        model.apply(Decimal(0), buy=True)
