"""Passive benchmark: hand-accountable window arithmetic and refusals.

Golden trace (zero costs on the golden bars, capital 1000): the
benchmark fills where every strategy first can — the second bar's
open 102 — spends the whole capital minus a commission the model
charges (0 here), and marks the 98 close. With cash = 1000 - q * 102
the ending equity is exactly 1000 - q * (102 - 98) = 1000 - 4q: the
window fell, so the net return is strictly below zero.

With the default costs (5 bps commission, 10 bps slippage) the entry
is 102 * 1.001 = 102.102 exactly, the commission is the model's own
method applied to the model's own notional, and the drag can only
make the net return worse than the free one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from harsh_quant_os.backtesting import (
    BacktestConfig,
    BacktestError,
    PassiveBenchmark,
    passive_benchmark,
)
from harsh_quant_os.backtesting.costs import BpsCommission, FixedBpsSlippage
from tests.backtesting.test_engine import GOLDEN_BARS, _bar, _config, _data

pytestmark = pytest.mark.backtesting

_ZERO = _config(commission_bps="0", slippage_bps="0")


class _ZeroSlip:
    """A slippage model that prices every buy at nothing — refused."""

    def apply(self, reference: Decimal, *, buy: bool) -> Decimal:
        return Decimal(0)


def _benchmark(**overrides: object) -> PassiveBenchmark:
    """A self-consistent benchmark: 9 units at 102, cash 82, close 98.

    Hand identities: 9 * 102 + 0 + 82 = 1000 (the capital), and
    9 * 98 + 82 = 964 (the ending), net 964 / 1000 - 1 = -0.036.
    """
    fields: dict[str, object] = {
        "entry_time": datetime(2024, 1, 1, 0, 1, tzinfo=UTC),
        "entry_reference": Decimal(102),
        "entry_price": Decimal(102),
        "quantity": Decimal(9),
        "commission": Decimal(0),
        "cash_left": Decimal(82),
        "last_close": Decimal(98),
        "ending_equity": Decimal(964),
        "net_return": Decimal("-0.036"),
        "bars": 5,
        "starting_capital": Decimal(1000),
        "assumptions": (("role", "test fixture"),),
    }
    fields.update(overrides)
    return PassiveBenchmark(**fields)  # type: ignore[arg-type]


def test_zero_cost_golden_benchmark_is_hand_accountable() -> None:
    benchmark = passive_benchmark(_data(), config=_ZERO)

    assert benchmark.entry_time == GOLDEN_BARS[1].timestamp
    assert benchmark.entry_reference == Decimal(102)
    assert benchmark.entry_price == Decimal(102)
    assert benchmark.commission == Decimal(0)
    assert benchmark.last_close == Decimal(98)
    assert (benchmark.bars, benchmark.starting_capital) == (5, Decimal(1000))

    assert benchmark.quantity * benchmark.entry_price <= Decimal(1000)
    assert benchmark.cash_left >= 0
    assert benchmark.cash_left == Decimal(1000) - benchmark.quantity * benchmark.entry_price
    assert benchmark.ending_equity == Decimal(1000) - Decimal(4) * benchmark.quantity
    assert benchmark.net_return == benchmark.ending_equity / Decimal(1000) - 1
    assert benchmark.net_return < 0  # 102 -> 98: a falling window

    assumptions = dict(benchmark.assumptions)
    assert "long only" in assumptions["direction"]
    assert "second bar open" in assumptions["entry"]
    assert "no exit fee" in assumptions["marking"]


def test_costed_benchmark_uses_the_models_own_methods() -> None:
    config = _config()  # 5 bps commission, 10 bps slippage
    benchmark = passive_benchmark(_data(), config=config)

    assert benchmark.entry_price == Decimal("102.102")  # 102 * (1 + 10/10000)
    assert benchmark.commission == config.commission.apply(
        benchmark.quantity * benchmark.entry_price
    )
    assert (
        benchmark.quantity * benchmark.entry_price + benchmark.commission + benchmark.cash_left
        == Decimal(1000)
    )
    assert benchmark.cash_left >= 0
    assert benchmark.commission > 0

    free = passive_benchmark(_data(), config=_ZERO)
    assert benchmark.net_return < free.net_return  # costs only drag


def test_a_window_without_a_second_bar_is_refused() -> None:
    with pytest.raises(BacktestError, match="second bar"):
        passive_benchmark(_data((_bar(0, "100", "100"),)), config=_ZERO)


def test_a_non_positive_close_is_refused() -> None:
    bars = (
        _bar(0, "100", "100"),
        _bar(1, "102", "104"),
        _bar(2, "105", "103"),
        _bar(3, "101", "100"),
        _bar(4, "99", "0"),
    )
    with pytest.raises(BacktestError, match="break both"):
        passive_benchmark(_data(bars), config=_ZERO)


def test_a_non_positive_entry_reference_is_refused() -> None:
    bars = (_bar(0, "100", "100"), _bar(1, "0", "104"), _bar(2, "105", "103"))
    with pytest.raises(BacktestError, match="entry reference"):
        passive_benchmark(_data(bars), config=_ZERO)


def test_a_slippage_model_that_prices_zero_is_refused() -> None:
    config = BacktestConfig(
        starting_capital=Decimal(1000),
        commission=BpsCommission(rate_bps=Decimal(0)),
        slippage=_ZeroSlip(),
    )
    with pytest.raises(BacktestError, match="non-positive price"):
        passive_benchmark(_data(), config=config)


def test_commission_eating_the_capital_is_refused_not_approximated() -> None:
    config = BacktestConfig(
        starting_capital=Decimal(1000),
        commission=BpsCommission(rate_bps=Decimal(5), fixed_fee=Decimal(2000)),
        slippage=FixedBpsSlippage(bps=Decimal(0)),
    )
    with pytest.raises(BacktestError, match="consume the benchmark"):
        passive_benchmark(_data(), config=config)


def test_a_self_consistent_benchmark_passes_and_the_broken_ones_do_not() -> None:
    # The fixture's own identities hold.
    valid = _benchmark()
    assert valid.ending_equity == Decimal(964)
    assert valid.net_return == Decimal("-0.036")

    with pytest.raises(BacktestError, match="at least two bars"):
        _benchmark(bars=1)
    with pytest.raises(BacktestError, match="starting capital must be positive"):
        _benchmark(starting_capital=Decimal(0))
    with pytest.raises(BacktestError, match="quantity must be a positive"):
        _benchmark(quantity=Decimal(-9))
    with pytest.raises(BacktestError, match="cash_left must be a non-negative"):
        _benchmark(cash_left=Decimal(-1))
    with pytest.raises(BacktestError, match="own marking"):
        _benchmark(ending_equity=Decimal(965))
    with pytest.raises(BacktestError, match="own return"):
        _benchmark(net_return=Decimal(0))
    with pytest.raises(BacktestError, match="without its assumptions"):
        _benchmark(assumptions=())
    with pytest.raises(BacktestError, match="an empty one is refused"):
        _benchmark(assumptions=(("role", "   "),))


def test_the_assumptions_say_what_the_rule_is() -> None:
    benchmark = passive_benchmark(_data(), config=_ZERO)
    assumptions = dict(benchmark.assumptions)
    assert assumptions["costs"].startswith("the configured commission")
    assert all(value.strip() for value in assumptions.values())
