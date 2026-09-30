"""Out-of-sample discipline: chronological splits, held-out touched once.

Phase 7 increment 1 turns anti-overfitting.md §2.2 (data separation)
into code that can refuse:

- :func:`train_test_split` cuts a pinned dataset chronologically — no
  shuffle, no look-ahead: the held-out suffix starts strictly after
  the last training bar.
- :class:`AccessLedger` records every access to a split's slices and
  refuses a second touch of the held-out slice outright. Repeatedly
  consulting the test set converts it into training data, so a second
  attempt must fail loudly instead of being logged quietly.
- :func:`evaluate_held_out` runs a strategy on the held-out slice
  exactly once, first verifying that the data handed in really is
  this split's suffix, and returns the §3 manifest beside the §4
  numbers.
- :func:`select_on_train` runs every declared candidate on the
  training slice under an explicit :class:`SelectionObjective` and
  records the whole trace — every variant tried, what each scored,
  each run's manifest — so the selection step is reproducible and the
  multiple-testing count is visible rather than implied.

Selection ranks by highest score; ties resolve to the first candidate
in the declared order and are recorded in the trace, so a tie can
never pass for a decisive win. Candidates are factories
(:class:`Candidate`): strategies are per-run objects, like risk
evaluators — one window's decisions must not be able to depend on
another window's history.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from harsh_quant_os.backtesting.data import BacktestData
from harsh_quant_os.backtesting.engine import BacktestConfig, BacktestResult, run_backtest
from harsh_quant_os.backtesting.errors import BacktestError
from harsh_quant_os.backtesting.manifest import build_manifest
from harsh_quant_os.backtesting.metrics import compute_metrics
from harsh_quant_os.backtesting.strategy import Strategy
from harsh_quant_os.safety.risk import RiskEvaluator

__all__ = [
    "ENDING_EQUITY",
    "AccessLedger",
    "Candidate",
    "CandidateRun",
    "DataSplit",
    "HeldOutEvaluation",
    "LedgerEntry",
    "OutOfSampleNumbers",
    "SelectionObjective",
    "SelectionTrace",
    "evaluate_held_out",
    "select_on_train",
    "train_test_split",
]


# ---------------------------------------------------------------------------
# The cut
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DataSplit:
    """The cut line between selection data and data never used for selection.

    Attributes:
        dataset_id / dataset_version: The pinned artefact the split
            belongs to — a cut is meaningless without it.
        train_start / train_end: First and last training bar
            timestamps (inclusive).
        test_start / test_end: First and last held-out bar timestamps
            (inclusive); ``train_end < test_start`` always.
        train_bars / test_bars: Slice sizes.
    """

    dataset_id: str
    dataset_version: str
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train_bars: int
    test_bars: int

    def __post_init__(self) -> None:
        if self.train_bars < 1 or self.test_bars < 1:
            raise BacktestError(
                "a split has at least one bar on each side; got "
                f"train_bars={self.train_bars}, test_bars={self.test_bars}"
            )
        if self.train_start > self.train_end:
            raise BacktestError(
                f"training span {self.train_start.isoformat()} to "
                f"{self.train_end.isoformat()} runs backwards"
            )
        if self.test_start > self.test_end:
            raise BacktestError(
                f"held-out span {self.test_start.isoformat()} to "
                f"{self.test_end.isoformat()} runs backwards"
            )
        if self.train_end >= self.test_start:
            raise BacktestError(
                "the held-out slice must start strictly after every training bar "
                f"(train ends {self.train_end.isoformat()}, test starts "
                f"{self.test_start.isoformat()}): overlap would leak the answer "
                "into the selection"
            )


def train_test_split(
    data: BacktestData, *, test_bars: int
) -> tuple[BacktestData, BacktestData, DataSplit]:
    """Chronological train / held-out cut of a pinned dataset.

    The cut is by position, never shuffled: time series split any
    other way leaks the future into the selection.

    Args:
        data: The pinned dataset to cut.
        test_bars: Size of the held-out suffix. Must leave at least
            one training bar and keep at least one held-out bar.

    Returns:
        ``(train, held_out, split)`` — two slices of the same
        artefact plus the record describing the cut.

    Raises:
        BacktestError: ``test_bars`` outside ``1..len(bars) - 1``.
    """
    count = len(data.bars)
    if test_bars < 1 or test_bars >= count:
        raise BacktestError(
            "held-out suffix must leave at least one training bar and keep at "
            f"least one held-out bar: test_bars={test_bars} against {count} bars "
            f"(valid range 1..{count - 1})"
        )
    cut = count - test_bars
    train = data.span(0, cut)
    held_out = data.span(cut, count)
    split = DataSplit(
        dataset_id=data.dataset_id,
        dataset_version=data.version,
        train_start=train.bars[0].timestamp,
        train_end=train.bars[-1].timestamp,
        test_start=held_out.bars[0].timestamp,
        test_end=held_out.bars[-1].timestamp,
        train_bars=cut,
        test_bars=test_bars,
    )
    return train, held_out, split


# ---------------------------------------------------------------------------
# The access ledger (anti-overfitting §2.2: every access is recorded)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One recorded access to one side of a split.

    Attributes:
        slice_name: ``"train"`` or ``"held-out"``.
        purpose: Why the slice was touched (e.g.
            ``"candidate selection"``, ``"held-out evaluation"``).
        dataset_id / dataset_version: The artefact touched.
        start / end: First and last bar timestamps of the touch.
    """

    slice_name: str
    purpose: str
    dataset_id: str
    dataset_version: str
    start: datetime
    end: datetime


class AccessLedger:
    """Append-only record of every access to a split.

    Immutable by construction: :meth:`record` returns a new ledger, so
    the trail cannot be edited in place. The held-out slice may appear
    at most once — a second attempt raises instead of quietly logging
    it (anti-overfitting §2.2).
    """

    def __init__(self, entries: Sequence[LedgerEntry] = ()) -> None:
        self._entries = tuple(entries)

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        """Every recorded access, oldest first."""
        return self._entries

    @property
    def held_out_touches(self) -> int:
        """How many times the held-out slice has been accessed (0 or 1)."""
        return sum(1 for entry in self._entries if entry.slice_name == "held-out")

    def record_split(self, *, slice_name: str, purpose: str, split: DataSplit) -> AccessLedger:
        """Record access to one side of ``split``; returns a new ledger.

        Raises:
            BacktestError: Unknown slice name, or a second held-out
                touch — the test set becomes training data the moment
                it is consulted twice, so the protocol refuses.
        """
        if slice_name not in {"train", "held-out"}:
            raise BacktestError(
                f"unknown slice {slice_name!r} (the ledger knows 'train' and "
                "'held-out'); refusing to record something it cannot name"
            )
        if slice_name == "held-out" and self.held_out_touches:
            raise BacktestError(
                "the held-out slice has already been accessed; the protocol "
                "touches it once (anti-overfitting §2.2) — a second touch would "
                "convert it into training data, so it is refused, not logged"
            )
        entry = LedgerEntry(
            slice_name=slice_name,
            purpose=purpose,
            dataset_id=split.dataset_id,
            dataset_version=split.dataset_version,
            start=split.test_start if slice_name == "held-out" else split.train_start,
            end=split.test_end if slice_name == "held-out" else split.train_end,
        )
        return AccessLedger((*self._entries, entry))


# ---------------------------------------------------------------------------
# What one held-out run produced
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutOfSampleNumbers:
    """The few numbers out-of-sample evidence needs, taken from one run.

    Attributes:
        net_return: ``(ending equity / starting capital) - 1`` — after
            the recorded costs, including the mark on any position
            still open at the slice's final bar.
        ending_equity: Final marked equity (exact).
        filled: Orders that actually executed.
        round_trips / wins / losses / breakeven: Completed cycle split
            under §4's rules (breakeven excluded from hit rate).
        open_at_end: A position was still held at the slice's final
            bar — its outcome is not in ``round_trips``.
        commission: Fees paid inside this slice (exact).
    """

    net_return: Decimal
    ending_equity: Decimal
    filled: int
    round_trips: int
    wins: int
    losses: int
    breakeven: int
    open_at_end: bool
    commission: Decimal

    @classmethod
    def from_result(cls, result: BacktestResult) -> OutOfSampleNumbers:
        """Extract the numbers from a finished run (no re-computation)."""
        trade = compute_metrics(result).trades
        net = result.ending_equity / result.starting_capital - Decimal(1)
        return cls(
            net_return=net,
            ending_equity=result.ending_equity,
            filled=len(result.filled),
            round_trips=trade.round_trips,
            wins=trade.wins,
            losses=trade.losses,
            breakeven=trade.breakeven,
            open_at_end=trade.open_position_at_end,
            commission=result.total_commission,
        )


# ---------------------------------------------------------------------------
# Selection on the training slice
# ---------------------------------------------------------------------------


def _ending_equity(result: BacktestResult) -> Decimal:
    return result.ending_equity


@dataclass(frozen=True, slots=True)
class SelectionObjective:
    """How candidate runs are ranked on the training slice.

    Attributes:
        name: Recorded in every trace — an unnamed objective would
            make the selection unreadable after the fact.
        score: Pure function from a finished run to a ``Decimal``;
            higher wins.
    """

    name: str
    score: Callable[[BacktestResult], Decimal]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise BacktestError("a selection objective must name itself for the record")

    def __call__(self, result: BacktestResult) -> Decimal:
        value = self.score(result)
        if not isinstance(value, Decimal) or not value.is_finite():
            raise BacktestError(
                f"objective {self.name!r} must return a finite Decimal, got "
                f"{value!r}; refusing to rank candidates on it"
            )
        return value


#: Default objective: the training slice's ending equity, costs as
#: configured. Explicit because every selection needs one — there is
#: no implicit default in this codebase.
ENDING_EQUITY = SelectionObjective(name="ending_equity", score=_ending_equity)


@dataclass(frozen=True, slots=True)
class Candidate:
    """One declared parameter variant: a label and a fresh-instance builder.

    Strategies are per-run objects (the reproduction contract in
    :func:`~harsh_quant_os.backtesting.manifest.run_from_manifest`),
    so every run calls :meth:`fresh` instead of reusing an instance
    whose hidden state could carry across slices.

    Attributes:
        label: Distinct, non-empty name recorded in every trace.
        build: Zero-argument builder for a new strategy instance.
    """

    label: str
    build: Callable[[], Strategy]

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise BacktestError("each candidate needs a label the trace can name")

    def fresh(self) -> Strategy:
        """Build a new strategy instance for one run."""
        return self.build()


@dataclass(frozen=True, slots=True)
class CandidateRun:
    """One candidate scored on one slice, with its §3 manifest attached.

    Attributes:
        label: The candidate's label.
        score: The objective's value for this run.
        manifest: The run's full manifest — the evidence another run
            can reproduce this number from.
    """

    label: str
    score: Decimal
    manifest: dict[str, object]


@dataclass(frozen=True, slots=True)
class SelectionTrace:
    """The whole selection: every variant tried, scores, and the winner.

    Attributes:
        selected: Winning label — the first declared candidate among
            ties.
        tied: Every label at the winning score, in declared order
            (always at least the winner; more than one means a tie
            happened, and it is reported as such).
        objective: The objective's recorded name.
        runs: One entry per candidate, in declared order — the
            multiple-testing count is ``len(runs)``, not a secret.
    """

    selected: str
    tied: tuple[str, ...]
    objective: str
    runs: tuple[CandidateRun, ...]

    def __post_init__(self) -> None:
        labels = [run.label for run in self.runs]
        if not labels:
            raise BacktestError("a selection trace carries at least one run")
        if len(set(labels)) != len(labels):
            raise BacktestError(
                "duplicate candidate labels in a selection trace: every variant "
                "must be nameable on its own"
            )
        if self.selected not in labels:
            raise BacktestError(f"selected {self.selected!r} is not among the runs {labels!r}")
        if not self.tied or self.tied[0] != self.selected:
            raise BacktestError(
                "the tied record must open with the selected candidate; got "
                f"tied={self.tied!r}, selected={self.selected!r}"
            )
        if not self.objective.strip():
            raise BacktestError("a selection trace records the objective it ranked under")
        scores = {run.label: run.score for run in self.runs}
        top = max(scores.values())
        if scores[self.selected] != top:
            raise BacktestError(
                f"selected {self.selected!r} scored {scores[self.selected]}, "
                f"which is not the top score {top}"
            )
        expected = tuple(label for label in labels if scores[label] == top)
        if self.tied != expected:
            raise BacktestError(
                f"tied record {self.tied!r} does not match the scores (expected {expected!r})"
            )


def select_on_train(
    train: BacktestData,
    *,
    candidates: Sequence[Candidate],
    config: BacktestConfig,
    risk_factory: Callable[[], RiskEvaluator],
    objective: SelectionObjective = ENDING_EQUITY,
) -> SelectionTrace:
    """Run every candidate on the training slice and record the whole race.

    Each candidate gets a **fresh** strategy instance and a **fresh**
    risk evaluator (both are per-run objects), and each run's manifest
    is kept beside its score so the selection itself is reproducible.

    Args:
        train: The training slice — never the held-out one.
        candidates: The declared variants, in declared order.
        config: Capital and cost models, identical for every run.
        risk_factory: Builds one fresh evaluator per run.
        objective: Ranking rule; recorded by name in the trace.

    Returns:
        The full trace with the winner resolved (ties to the first
        declared candidate, recorded).

    Raises:
        BacktestError: No candidates, or an objective returning
            something other than a finite ``Decimal``.
    """
    if not candidates:
        raise BacktestError("selection needs at least one candidate")
    runs: list[CandidateRun] = []
    for candidate in candidates:
        risk = risk_factory()
        strategy = candidate.fresh()
        result = run_backtest(train, strategy, config, risk=risk)
        manifest = build_manifest(result, config=config, risk=risk)
        runs.append(CandidateRun(label=candidate.label, score=objective(result), manifest=manifest))
    scores = [run.score for run in runs]
    top = max(scores)
    tied = tuple(run.label for run in runs if run.score == top)
    return SelectionTrace(
        selected=tied[0],
        tied=tied,
        objective=objective.name,
        runs=tuple(runs),
    )


# ---------------------------------------------------------------------------
# The held-out evaluation (touched once)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HeldOutEvaluation:
    """One strategy, evaluated on the held-out slice exactly once.

    Attributes:
        split: The split this evaluation belongs to.
        numbers: The §4 numbers of the held-out run.
        manifest: The run's §3 manifest — the evidence.
        ledger: The ledger with this evaluation's access recorded.
    """

    split: DataSplit
    numbers: OutOfSampleNumbers
    manifest: dict[str, object]
    ledger: AccessLedger


def evaluate_held_out(
    test: BacktestData,
    *,
    split: DataSplit,
    strategy: Strategy,
    config: BacktestConfig,
    risk: RiskEvaluator,
    ledger: AccessLedger,
) -> HeldOutEvaluation:
    """Run one strategy on the held-out slice, once, under a ledger.

    Fails closed, in order: the data handed in must be the split's
    pinned held-out slice (same artefact, same span); the ledger must
    not already contain a held-out touch. Only then does the run
    happen, and the returned evaluation carries the updated ledger.

    Args:
        test: The held-out slice — must match ``split`` exactly.
        split: The split that defines what "held-out" means here.
        strategy: The strategy to evaluate (one fresh instance's run).
        config: Capital and cost models.
        risk: A fresh evaluator for this run.
        ledger: The access ledger to check and extend.

    Returns:
        The evaluation with numbers, manifest and updated ledger.

    Raises:
        BacktestError: Slice/artefact mismatch with the split, or a
            second held-out touch recorded in the ledger.
    """
    if test.dataset_id != split.dataset_id or test.version != split.dataset_version:
        raise BacktestError(
            "the data handed in is not the split's pinned artefact "
            f"({split.dataset_id}@{split.dataset_version[:12]}): refusing to "
            "evaluate a different dataset under a held-out label"
        )
    if (
        len(test.bars) != split.test_bars
        or test.bars[0].timestamp != split.test_start
        or test.bars[-1].timestamp != split.test_end
    ):
        raise BacktestError(
            "the data handed in is not the held-out slice this split describes "
            f"(split: {split.test_bars} bars, {split.test_start.isoformat()} to "
            f"{split.test_end.isoformat()}); refusing to evaluate a different "
            "window under a held-out label"
        )
    # The ledger's own refusal fires here on a second touch, before
    # the strategy sees a single bar.
    recorded = ledger.record_split(
        slice_name="held-out", purpose="held-out evaluation", split=split
    )
    result = run_backtest(test, strategy, config, risk=risk)
    manifest = build_manifest(result, config=config, risk=risk)
    return HeldOutEvaluation(
        split=split,
        numbers=OutOfSampleNumbers.from_result(result),
        manifest=manifest,
        ledger=recorded,
    )
