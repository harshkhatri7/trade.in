"""Shuffled-signal null: golden capture, seeded replay, count semantics.

Golden trace (zero costs on the golden bars): the declared strategy is
consulted once per bar and decides (0, 2, 2, 0, 0) — close 100 is not
above 100, then 104/103 are, then 100/98 are not — so the capture run
itself scores 988, the golden ending equity. A strategy that answers
the same value on every bar shuffles to itself: all trials score 996
(target 1 bought at the second bar's open 102, marked at 98, zero
costs: 1000 - 102 + 98), so the report's fraction is exactly 1 —
timing carried nothing, which is exactly what the count is for.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal

import pytest

from harsh_quant_os.backtesting import (
    BacktestError,
    DecisionContext,
    ShuffledNull,
    Strategy,
    shuffle_null,
)
from tests.backtesting.test_engine import ApproveAll, _config, _data

pytestmark = pytest.mark.backtesting

_ZERO = _config(commission_bps="0", slippage_bps="0")


class RecordingThreshold:
    """The golden rule, remembering the value it returned each bar."""

    name = "threshold"

    def __init__(self) -> None:
        self.decided: list[Decimal | None] = []

    def decide(self, context: DecisionContext) -> Decimal | None:
        value = Decimal(2) if context.bar.close > 100 else Decimal(0)
        self.decided.append(value)
        return value

    def describe(self) -> Mapping[str, str]:
        return {"target_qty": "2", "entry": "close > 100"}


class AlwaysBuy:
    """Target 1 on every bar: identical signals, so shuffling is a no-op."""

    name = "always-buy"

    def decide(self, context: DecisionContext) -> Decimal | None:
        return Decimal(1)

    def describe(self) -> Mapping[str, str]:
        return {"rule": "target 1 on every bar"}


def _run(
    build: Callable[[], Strategy],
    *,
    seed: int = 42,
    trials: int = 5,
) -> ShuffledNull:
    return shuffle_null(
        _data(),
        strategy_factory=build,
        config=_ZERO,
        risk_factory=ApproveAll,
        trials=trials,
        seed=seed,
    )


def test_capture_records_one_decision_per_bar_and_scores_the_real_run() -> None:
    made: list[RecordingThreshold] = []

    def factory() -> RecordingThreshold:
        strategy = RecordingThreshold()
        made.append(strategy)
        return strategy

    report = _run(factory)

    assert len(made) == 1  # consulted exactly once: the capture
    assert made[0].decided == [
        Decimal(0),
        Decimal(2),
        Decimal(2),
        Decimal(0),
        Decimal(0),
    ]
    assert report.objective == "ending_equity"
    assert report.actual == Decimal(988)
    assert report.trials == 5
    assert (report.bars, report.decisions, report.seed) == (5, 5, 42)
    assert len(report.scores) == 5
    assert all(score.is_finite() for score in report.scores)
    assert any(score != report.actual for score in report.scores)  # a shuffle bites
    assert "not the probability" in report.note


def test_the_same_seed_replays_the_same_trials() -> None:
    first = _run(RecordingThreshold, seed=42, trials=5)
    second = _run(RecordingThreshold, seed=42, trials=5)
    assert first == second

    other = _run(RecordingThreshold, seed=7, trials=5)
    assert other.scores != first.scores  # the seed decides which permutations


def test_identical_signals_make_the_fraction_exactly_one() -> None:
    report = _run(AlwaysBuy, seed=42, trials=7)

    assert report.actual == Decimal(996)
    assert report.scores == (Decimal(996),) * 7
    assert report.matching_or_beating == 7
    assert report.extreme_fraction == Decimal(1)
    assert report.null_lowest == report.null_highest == Decimal(996)


def test_a_null_that_ran_nothing_or_cannot_identify_itself_is_refused() -> None:
    with pytest.raises(BacktestError, match="at least one trial"):
        _run(RecordingThreshold, trials=0)
    with pytest.raises(BacktestError, match="trials must be an int"):
        _run(RecordingThreshold, trials=2.5)  # type: ignore[arg-type]
    with pytest.raises(BacktestError, match="seed must be an int"):
        _run(RecordingThreshold, seed=4.2)  # type: ignore[arg-type]


def _report(**overrides: object) -> ShuffledNull:
    """A self-consistent report: 2 of 3 trials matched or beat 988."""
    fields: dict[str, object] = {
        "objective": "ending_equity",
        "actual": Decimal(988),
        "scores": (Decimal(980), Decimal(988), Decimal(1000)),
        "seed": 42,
        "bars": 5,
        "decisions": 5,
        "note": "a plain count over this design",
    }
    fields.update(overrides)
    return ShuffledNull(**fields)  # type: ignore[arg-type]


def test_the_counts_follow_from_the_scores() -> None:
    report = _report()

    assert report.trials == 3
    assert report.matching_or_beating == 2  # the 988 tie and the 1000
    assert report.extreme_fraction == Decimal(2) / Decimal(3)
    assert report.null_lowest == Decimal(980)
    assert report.null_highest == Decimal(1000)


def test_a_report_that_cannot_account_for_itself_is_refused() -> None:
    with pytest.raises(BacktestError, match="name its objective"):
        _report(objective="   ")
    with pytest.raises(BacktestError, match="actual score must be a finite"):
        _report(actual=Decimal("NaN"))
    with pytest.raises(BacktestError, match="no trials"):
        _report(scores=())
    with pytest.raises(BacktestError, match="must be a finite decimal"):
        _report(scores=(Decimal("NaN"),))
    with pytest.raises(BacktestError, match="seed must be an int"):
        _report(seed=4.2)
    with pytest.raises(BacktestError, match="nothing to shuffle"):
        _report(bars=0, decisions=0)
    with pytest.raises(BacktestError, match="never padded"):
        _report(decisions=4)
    with pytest.raises(BacktestError, match="carries its note"):
        _report(note="   ")
