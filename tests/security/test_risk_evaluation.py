"""Risk-evaluation tests: the fail-closed evaluator over Settings limits.

The evaluator behind backtesting.md §8 criterion 6 — every simulated
order passes through it, and these tests pin its refusal behaviour:
limits naming both numbers, reducing orders never blocked, the
daily-loss cycle resetting with the UTC date, unparseable inputs
refusing with reasons (risk-engine.md §6), and a live configuration
unable to build it at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest

from harsh_quant_os.config import Settings
from harsh_quant_os.safety import (
    ConfiguredRiskEvaluator,
    LiveTradingBlockedError,
    RiskEvaluation,
)

pytestmark = [pytest.mark.security, pytest.mark.unit]

_DAY_ONE = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
_DAY_TWO = datetime(2024, 1, 2, 12, 0, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    return Settings.load(_env_file=None, **overrides)


def _evaluate(
    evaluator: ConfiguredRiskEvaluator,
    *,
    time: datetime = _DAY_ONE,
    position: Decimal = Decimal(0),
    delta: Decimal = Decimal(1),
    price: Decimal = Decimal(10),
    equity: Decimal = Decimal(1000),
) -> RiskEvaluation:
    return evaluator.evaluate(
        decision_time=time,
        position=position,
        delta=delta,
        price=price,
        equity=equity,
    )


def test_a_live_configuration_cannot_build_the_evaluator() -> None:
    # model_construct bypasses Settings' own load-time rejection, so
    # this exercises the evaluator's constructor guard directly.
    live = Settings.model_construct(live_trading_enabled=True)
    with pytest.raises(LiveTradingBlockedError):
        ConfiguredRiskEvaluator(live)


def test_small_orders_are_approved_under_default_limits() -> None:
    evaluator = ConfiguredRiskEvaluator(_settings())
    verdict = _evaluate(evaluator, delta=Decimal(2), price=Decimal("105.105"))
    assert verdict.approved
    assert verdict.reason == ""


def test_position_notional_refusal_names_both_numbers_and_the_limit() -> None:
    evaluator = ConfiguredRiskEvaluator(_settings())
    verdict = _evaluate(evaluator, delta=Decimal(2), price=Decimal(60_000))
    assert not verdict.approved
    assert "120000" in verdict.reason  # resulting notional: 2 * 60000
    assert "RISK_MAX_POSITION_NOTIONAL" in verdict.reason
    assert "100000.0" in verdict.reason  # the exact decimal captured from Settings


def test_a_custom_limit_is_captured_exactly() -> None:
    evaluator = ConfiguredRiskEvaluator(_settings(risk_max_position_notional=50.0))
    verdict = _evaluate(evaluator, delta=Decimal(1), price=Decimal(60))
    assert not verdict.approved
    assert "60" in verdict.reason and "50.0" in verdict.reason
    # one tick under the limit still passes
    assert _evaluate(evaluator, delta=Decimal(1), price=Decimal("49.99")).approved


def test_reducing_orders_are_never_blocked() -> None:
    evaluator = ConfiguredRiskEvaluator(_settings(risk_max_daily_loss=100.0))
    # Establish a day with a large loss: day start 1000, now 850.
    first = _evaluate(evaluator, equity=Decimal(1000))
    assert first.approved
    breached = _evaluate(evaluator, equity=Decimal(850), price=Decimal(5))
    assert not breached.approved  # risk-increasing into a breached day

    # Exiting, however, is allowed even deep in the loss and over the
    # notional limit: a risk engine never blocks the way out.
    reducing = _evaluate(
        evaluator,
        position=Decimal(10_000),
        delta=Decimal(-1),
        price=Decimal(60_000),
        equity=Decimal(850),
    )
    assert reducing.approved

    flatting = _evaluate(
        evaluator,
        position=Decimal(10_000),
        delta=Decimal(-10_000),
        price=Decimal(60_000),
        equity=Decimal(850),
    )
    assert flatting.approved


def test_daily_loss_refuses_until_the_next_utc_date() -> None:
    evaluator = ConfiguredRiskEvaluator(_settings(risk_max_daily_loss=100.0))

    assert _evaluate(evaluator, equity=Decimal(1000)).approved  # day start
    loss = _evaluate(evaluator, equity=Decimal(850))  # 150 > 100
    assert not loss.approved
    assert "daily loss 150" in loss.reason
    assert "RISK_MAX_DAILY_LOSS 100.0" in loss.reason

    # Same date, risk-increasing still refused; a new date resets the mark.
    assert not _evaluate(evaluator, equity=Decimal(800)).approved
    assert _evaluate(evaluator, time=_DAY_TWO, equity=Decimal(800)).approved

    # And the new date's own loss is measured from its own opening mark.
    assert not _evaluate(evaluator, time=_DAY_TWO, equity=Decimal(650)).approved


def test_unparseable_inputs_refuse_with_a_reason() -> None:
    evaluator = ConfiguredRiskEvaluator(_settings())

    float_equity = _evaluate(evaluator, equity=cast(Decimal, 1.5))
    assert not float_equity.approved
    assert "unparseable equity" in float_equity.reason

    nan_price = _evaluate(evaluator, price=Decimal("NaN"))
    assert not nan_price.approved
    assert "non-finite" in nan_price.reason

    naive = _evaluate(evaluator, time=datetime(2024, 1, 1, 12, 0))
    assert not naive.approved
    assert "naive timestamp" in naive.reason

    inf_position = _evaluate(evaluator, position=Decimal("Infinity"))
    assert not inf_position.approved
    assert "non-finite" in inf_position.reason


def test_constructor_refuses_invalid_limits_rather_than_approving_them() -> None:
    with pytest.raises(ValueError, match="RISK_MAX_POSITION_NOTIONAL"):
        ConfiguredRiskEvaluator(Settings.model_construct(risk_max_position_notional=0.0))
    with pytest.raises(ValueError, match="RISK_MAX_DAILY_LOSS"):
        ConfiguredRiskEvaluator(Settings.model_construct(risk_max_daily_loss=-1.0))
    with pytest.raises(ValueError, match="RISK_MAX_OPEN_POSITIONS"):
        ConfiguredRiskEvaluator(Settings.model_construct(risk_max_open_positions=0))


def test_a_fresh_evaluator_walked_again_gives_the_same_verdicts() -> None:
    # Determinism over the call sequence (the manifest-reproducibility
    # rule): two fresh instances, identical calls, identical verdicts.
    calls = (
        (Decimal(1000), Decimal(1)),
        (Decimal(900), Decimal(1)),
        (Decimal(700), Decimal(1)),
        (Decimal(950), Decimal(-1)),
    )
    runs = []
    for _ in range(2):
        evaluator = ConfiguredRiskEvaluator(_settings(risk_max_daily_loss=100.0))
        runs.append([_evaluate(evaluator, equity=equity, delta=delta) for equity, delta in calls])
    assert runs[0] == runs[1]
