"""The shuffled-signal null: does the timing of the signals carry anything?

anti-overfitting.md §2.6: compare against "a randomly-timed (shuffled)
version of the same signals — if the shuffled version performs
similarly, the edge is noise."

Design commitments:

- **The decisions are captured, not re-derived.** The declared
  strategy is consulted exactly once (strategies are pure by
  contract — two runs decide identically, reference.py states it — so
  one capture *is* the strategy's decisions), and the null permutes
  that exact tuple across the bars: the same multiset of targets with
  its link to timing broken. Nothing is re-simulated from a rewritten
  rule, so the comparison is about timing and nothing else.
- **The seed is explicit and required.** There is no default: the
  caller must pass a seed, and the report carries it, because a null
  whose randomness is unrecorded cannot be reproduced or audited. The
  permutation is derived from the seeded generator's ``random()``
  values — the sequence Python documents as stable across versions —
  ordered by a stable sort, so ``(seed, trials, bar count)`` replays
  it exactly.
- **The engine does the work.** Every trial is a full run: same data,
  same config, same cost models, a fresh risk evaluator. The shuffled
  strategy is a thin exogenous-signal provider — on bar *i* it
  answers with the permuted decision for bar *i* and nothing else,
  with its manifest describing the null, the seed and the trial.
- **The report counts, it does not conclude.** Every trial's score is
  kept in trial order; there is no "best trial" view. The fraction
  reported is a plain count over the trials — no p-value language, no
  probability that the strategy has no edge. A high fraction is
  *consistent with* timing carrying nothing, which is what §2.6 asks
  the reader to consider.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from harsh_quant_os.backtesting.data import BacktestData
from harsh_quant_os.backtesting.engine import BacktestConfig, run_backtest
from harsh_quant_os.backtesting.errors import BacktestError
from harsh_quant_os.backtesting.strategy import DecisionContext, Strategy
from harsh_quant_os.backtesting.validation import ENDING_EQUITY, SelectionObjective
from harsh_quant_os.safety.risk import RiskEvaluator

__all__ = ["ShuffledNull", "shuffle_null"]


#: What the count is and is not — carried by every report so a reader
#: cannot mistake it for a significance test.
_NOTE = (
    "extreme_fraction is the share of these seeded shuffled trials whose "
    "score matched or beat the actual run; it is a plain count over this "
    "design, not the probability that the strategy has no edge. A value "
    "near 1 is consistent with the timing carrying nothing "
    "(anti-overfitting section 2.6)."
)


class _Recorder:
    """Consults the declared strategy once, recording every decision.

    The recording never influences the decision — it sits in front of
    the strategy and passes the context through untouched.
    """

    def __init__(self, inner: Strategy) -> None:
        self.name = inner.name
        self._inner = inner
        self.decisions: list[Decimal | None] = []

    def decide(self, context: DecisionContext) -> Decimal | None:
        value = self._inner.decide(context)
        self.decisions.append(value)
        return value

    def describe(self) -> Mapping[str, str]:
        return dict(self._inner.describe())


class _ShuffledSignals:
    """Exogenous answers: bar *i* gets the permuted decision for bar *i*.

    No rule, no history read, no market view — the signal values and
    the seed they travelled under, and that is the whole strategy.
    """

    name = "shuffled-signals"

    def __init__(
        self,
        decisions: tuple[Decimal | None, ...],
        *,
        seed: int,
        trial: int,
        index_of: Mapping[datetime, int],
    ) -> None:
        self._decisions = decisions
        self._seed = seed
        self._trial = trial
        self._index_of = index_of

    def decide(self, context: DecisionContext) -> Decimal | None:
        try:
            index = self._index_of[context.bar.timestamp]
        except KeyError as error:
            raise BacktestError(
                f"the null received bar {context.bar.timestamp.isoformat()} "
                "which is not in the dataset it was built for: refusing to "
                "answer from another window"
            ) from error
        return self._decisions[index]

    def describe(self) -> Mapping[str, str]:
        return {
            "null": "shuffled-signals",
            "seed": str(self._seed),
            "trial": str(self._trial),
        }


@dataclass(frozen=True, slots=True)
class ShuffledNull:
    """The actual score beside the null distribution it was compared to.

    Attributes:
        objective: The objective's name — every score here is its
            output on a full run.
        actual: The declared strategy's own score on this data.
        scores: Every trial's score, in trial order. Nothing dropped,
        nothing summarised away.
        seed: The recorded seed — ``(seed, trials, bar count)``
            replays the permutation sequence exactly.
        bars: The window's bar count.
        decisions: Decisions captured (always ``bars``: the engine
            consults a strategy once per bar).
        note: The honesty note, carried with the numbers.

    Raises:
        BacktestError: An objective that does not name itself, a
        non-finite score, no scores, a seed that is not an int, a
        window that contradicts its decision count, or an empty note.
    """

    objective: str
    actual: Decimal
    scores: tuple[Decimal, ...]
    seed: int
    bars: int
    decisions: int
    note: str

    def __post_init__(self) -> None:
        if not self.objective.strip():
            raise BacktestError("a shuffled null must name its objective for the record")
        if not self.actual.is_finite():
            raise BacktestError(f"the actual score must be a finite decimal, got {self.actual}")
        if not self.scores:
            raise BacktestError(
                "a shuffled null with no trials counts nothing: the report is "
                "refused rather than presented empty"
            )
        for trial, score in enumerate(self.scores):
            if not score.is_finite():
                raise BacktestError(
                    f"trial {trial} scored {score}: every trial's score must "
                    "be a finite decimal, and a trial that is not is refused "
                    "rather than dropped"
                )
        raw_seed: object = self.seed
        if not isinstance(raw_seed, int):
            raise BacktestError(
                f"the null's seed must be an int recorded beside the result, "
                f"got {type(raw_seed).__name__}"
            )
        if self.bars < 1:
            raise BacktestError(f"a null over {self.bars} bars has nothing to shuffle")
        if self.decisions != self.bars:
            raise BacktestError(
                f"the null captured {self.decisions} decisions over {self.bars} "
                "bars: one per bar or the report is refused, never padded"
            )
        if not self.note.strip():
            raise BacktestError("a shuffled null carries its note: the count alone overstates")

    @property
    def trials(self) -> int:
        """How many shuffled runs were scored (``len(scores)``)."""
        return len(self.scores)

    @property
    def matching_or_beating(self) -> int:
        """Null trials whose score matched or beat the actual (ties count)."""
        return sum(1 for score in self.scores if score >= self.actual)

    @property
    def extreme_fraction(self) -> Decimal:
        """``matching_or_beating / trials``, exact — see the report's note.

        A plain count over this design: near 1 means the shuffled
        timing did as well as the real timing, which is consistent
        with the edge being in the signals' placement rather than
        their content. It is not a p-value and not the probability
        the strategy has no edge.
        """
        return Decimal(self.matching_or_beating) / Decimal(self.trials)

    @property
    def null_lowest(self) -> Decimal:
        """The worst shuffled trial's score."""
        return min(self.scores)

    @property
    def null_highest(self) -> Decimal:
        """The best shuffled trial's score."""
        return max(self.scores)


def shuffle_null(
    data: BacktestData,
    *,
    strategy_factory: Callable[[], Strategy],
    config: BacktestConfig,
    risk_factory: Callable[[], RiskEvaluator],
    objective: SelectionObjective = ENDING_EQUITY,
    trials: int,
    seed: int,
) -> ShuffledNull:
    """Score the declared strategy against its own re-timed signals.

    One capture run records the strategy's decision per bar; then each
    trial permutes that tuple across the bars with the seeded
    generator and runs the result through the engine as an
    exogenous-signal strategy.

    Args:
        data: The pinned dataset — the same slice being validated.
        strategy_factory: Builds the declared strategy; called **once**
            (the capture). Strategies are pure by contract, so that one
            run's decisions are the strategy's decisions.
        config: Capital and cost models, identical across every run.
        risk_factory: A fresh evaluator per run — capture and trials.
        objective: The headline rule, recorded by name; higher wins.
        trials: How many shuffled runs to score (at least 1; a handful
            of trials is weak evidence and the report shows the count).
        seed: Explicit, no default — record it beside the result.

    Returns:
        The report: actual score, every trial's score in order, the
        seed, and the counts derived from them.

    Raises:
        BacktestError: Fewer than one trial, a seed or trials value
        that is not an int, a strategy consulted a number of times
        other than once per bar, or any engine refusal from the runs
        themselves (surfaced, not swallowed).
    """
    raw_trials: object = trials
    if not isinstance(raw_trials, int):
        raise BacktestError(
            f"trials must be an int, got {type(raw_trials).__name__} (a null "
            "that cannot say how many runs it scored is refused)"
        )
    if trials < 1:
        raise BacktestError(
            f"a shuffled null needs at least one trial, got {trials}: a null "
            "that ran nothing counts nothing"
        )
    raw_seed: object = seed
    if not isinstance(raw_seed, int):
        raise BacktestError(
            f"the null's seed must be an int recorded beside the result, got "
            f"{type(raw_seed).__name__} — there is no default seed, because "
            "an unrecorded null cannot be reproduced"
        )

    recorder = _Recorder(strategy_factory())
    capture = run_backtest(data, recorder, config, risk=risk_factory())
    actual = objective(capture)
    decisions = tuple(recorder.decisions)
    if len(decisions) != len(data.bars):
        raise BacktestError(
            f"the strategy was consulted {len(decisions)} times over "
            f"{len(data.bars)} bars; the null shuffles one decision per bar "
            "and refuses to pad or trim"
        )

    index_of = {bar.timestamp: index for index, bar in enumerate(data.bars)}
    generator = random.Random(seed)
    scores: list[Decimal] = []
    for trial in range(trials):
        # Keyed on one stable-sort draw per element: the permutation
        # depends only on (seed, trials, bar count), never on the
        # shuffle implementation.
        order = sorted(range(len(decisions)), key=lambda _: generator.random())
        permuted = tuple(decisions[index] for index in order)
        shuffled = _ShuffledSignals(permuted, seed=seed, trial=trial, index_of=index_of)
        run = run_backtest(data, shuffled, config, risk=risk_factory())
        scores.append(objective(run))

    return ShuffledNull(
        objective=objective.name,
        actual=actual,
        scores=tuple(scores),
        seed=seed,
        bars=len(data.bars),
        decisions=len(decisions),
        note=_NOTE,
    )
