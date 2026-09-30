"""Deflated Sharpe: the headline prices the recorded shot count.

Golden traces, hand-checked:

- A symmetric series (+0.01, -0.01, +0.01, -0.01) has mean exactly
  zero, so its Sharpe is 0 and with one recorded shot SR0 is exactly
  0: the deflated value is Phi(0) = 0.5, bit for bit.
- The golden run's equity (1000, 1000, 996, 990, 988) has four
  strictly positive points and a strictly declining shape, so the
  deflation stands on 4 periods and lands below a half.
- Doubling every return doubles mean and stdev alike: the Sharpe,
  its variance and the deflation are scale-free, so the whole
  headline must come back identical.
- More recorded shots raise SR0 and lower the deflated value, for
  any series: the count is what deflates.
"""

from __future__ import annotations

import math
from dataclasses import replace
from decimal import Decimal
from statistics import NormalDist

import pytest

from harsh_quant_os.backtesting import (
    BacktestError,
    BacktestResult,
    DeflatedSharpe,
    deflated_from_result,
    deflated_sharpe,
    run_backtest,
)
from tests.backtesting.test_engine import ApproveAll, Threshold, _config, _data

pytestmark = pytest.mark.backtesting

_ZERO = _config(commission_bps="0", slippage_bps="0")

_MIXED = (
    Decimal("0.02"),
    Decimal("-0.01"),
    Decimal("0.005"),
    Decimal("0.01"),
    Decimal("-0.005"),
)


def _golden_run() -> BacktestResult:
    return run_backtest(_data(), Threshold(), _ZERO, risk=ApproveAll())


def _headline(**overrides: object) -> DeflatedSharpe:
    """A self-consistent headline: Sharpe 0, variance 1/3, one shot.

    Hand identities: sqrt(1/3) * 0 = 0 (the null expectation) and
    Phi((0 - 0) / sqrt(1/3)) = Phi(0) = 0.5 (the deflated value).
    """
    fields: dict[str, object] = {
        "sharpe": 0.0,
        "sr_variance": 1.0 / 3.0,
        "null_expected_max": 0.0,
        "deflated": 0.5,
        "trials": 1,
        "periods": 4,
        "skewness": 0.0,
        "kurtosis": 3.0,
        "note": "a plain count over this design",
    }
    fields.update(overrides)
    return DeflatedSharpe(**fields)  # type: ignore[arg-type]


def test_a_zero_sharpe_with_one_shot_deflates_to_a_half() -> None:
    report = deflated_sharpe(
        (Decimal("0.01"), Decimal("-0.01"), Decimal("0.01"), Decimal("-0.01")),
        trials=1,
    )

    assert report.sharpe == 0.0
    assert report.skewness == 0.0  # the series is symmetric
    assert report.null_expected_max == 0.0  # one shot: expected max is 0
    assert report.deflated == 0.5  # Phi(0), exactly
    assert (report.trials, report.periods) == (1, 4)
    assert "not the probability that the strategy works" in report.note


def test_the_headline_accounts_for_itself() -> None:
    report = deflated_sharpe(_MIXED, trials=7)

    gamma = 0.5772156649015328606
    normal = NormalDist()
    expected_max = (1 - gamma) * normal.inv_cdf(1 - 1 / 7) + gamma * normal.inv_cdf(
        1 - 1 / (7 * math.e)
    )
    assert report.null_expected_max == math.sqrt(report.sr_variance) * expected_max
    assert report.deflated == normal.cdf(
        (report.sharpe - report.null_expected_max) / math.sqrt(report.sr_variance)
    )
    assert report.periods == 5 and report.trials == 7
    assert 0.0 <= report.deflated <= 1.0
    assert report.shots_text == "shots"


def test_more_recorded_shots_lower_the_same_headline() -> None:
    one = deflated_sharpe(_MIXED, trials=1)
    two = deflated_sharpe(_MIXED, trials=2)
    fifty = deflated_sharpe(_MIXED, trials=50)

    assert one.null_expected_max < two.null_expected_max
    assert two.null_expected_max < fifty.null_expected_max
    assert one.deflated > two.deflated > fifty.deflated


def test_the_deflation_is_scale_free() -> None:
    plain = deflated_sharpe(_MIXED, trials=5)
    doubled = deflated_sharpe(tuple(value * 2 for value in _MIXED), trials=5)
    assert plain == doubled  # mean and stdev scale together: nothing changes


def test_from_result_deflates_the_runs_own_equity_returns() -> None:
    result = _golden_run()
    report = deflated_from_result(result, trials=3)

    assert report.periods == 4  # five equity points -> four returns
    assert report.trials == 3

    equities = [point.equity for point in result.equity_curve]
    returns = [equities[index] / equities[index - 1] - 1 for index in range(1, len(equities))]
    assert report == deflated_sharpe(returns, trials=3)

    # The same basis as VolatilityStats: mean/std, population, ddof=0.
    mean = sum(returns, Decimal(0)) / len(returns)
    squares = [(value - mean) ** 2 for value in returns]
    variance = sum(squares, Decimal(0)) / len(squares)
    assert report.sharpe == pytest.approx(float(mean / variance.sqrt()), rel=1e-12)

    assert report.sharpe < 0  # the golden curve declines (1000 -> 988)
    assert report.deflated < 0.5


def test_from_result_refuses_a_curve_it_cannot_ratio() -> None:
    result = _golden_run()
    one_point = replace(result, equity_curve=result.equity_curve[:1])
    with pytest.raises(BacktestError, match="two equity points"):
        deflated_from_result(one_point, trials=3)

    flat_floor = replace(
        result,
        equity_curve=(
            replace(result.equity_curve[0], equity=Decimal(0)),
            *result.equity_curve[1:],
        ),
    )
    with pytest.raises(BacktestError, match="non-positive account"):
        deflated_from_result(flat_floor, trials=3)


def test_the_runner_refuses_counts_and_series_it_cannot_trust() -> None:
    with pytest.raises(BacktestError, match="shot count must be an int"):
        deflated_sharpe(_MIXED, trials=2.5)  # type: ignore[arg-type]
    with pytest.raises(BacktestError, match="shot count must be an int"):
        deflated_sharpe(_MIXED, trials=True)  # bool is not a shot count
    with pytest.raises(BacktestError, match="at least one recorded shot"):
        deflated_sharpe(_MIXED, trials=0)
    with pytest.raises(BacktestError, match="at least two periods"):
        deflated_sharpe((Decimal("0.01"),), trials=3)
    with pytest.raises(BacktestError, match="not a Decimal"):
        deflated_sharpe((0.01, -0.01, 0.01), trials=3)  # type: ignore[arg-type]
    with pytest.raises(BacktestError, match="every period must be finite"):
        deflated_sharpe((Decimal("0.01"), Decimal("NaN"), Decimal("0.01")), trials=3)
    with pytest.raises(BacktestError, match="no variation"):
        deflated_sharpe((Decimal("0.01"), Decimal("0.01"), Decimal("0.01")), trials=3)


def test_a_headline_that_cannot_account_for_itself_is_refused() -> None:
    # The fixture's own identities hold.
    valid = _headline()
    assert valid.deflated == 0.5 and valid.null_expected_max == 0.0
    assert valid.shots_text == "shot"

    with pytest.raises(BacktestError, match="at least one recorded shot"):
        _headline(trials=0)
    with pytest.raises(BacktestError, match="shot count as an int"):
        _headline(trials=1.5)
    with pytest.raises(BacktestError, match="at least two periods"):
        _headline(periods=1)
    with pytest.raises(BacktestError, match="must be a finite float"):
        _headline(sharpe=float("inf"))
    with pytest.raises(BacktestError, match="positive variance"):
        _headline(sr_variance=0.0)
    with pytest.raises(BacktestError, match=r"within \[0, 1\]"):
        _headline(deflated=1.5)
    with pytest.raises(BacktestError, match="carries its note"):
        _headline(note="   ")
    with pytest.raises(BacktestError, match="own null expectation"):
        _headline(null_expected_max=0.1)
    with pytest.raises(BacktestError, match="cannot account for itself"):
        _headline(deflated=0.6)
