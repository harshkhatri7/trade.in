"""Validation contract: chronological splits, held-out once, recorded selection.

The load-bearing rules are anti-overfitting §2.2 made executable: the
cut is chronological (never shuffled), the held-out slice is touched
at most once and a second touch is refused rather than logged, data
handed in must be the split's own pinned slice, and selection records
every variant it tried with each run's manifest beside its score.

The held-out golden works the money out by hand: on the golden bars
with the golden costs, Threshold enters at t2's close, fills at t3
open 101 slippage-adjusted to 101.101 (notional 202.202, fee
0.101101), exits at t3's close (not > 100) filling t4 open 99
slippage-adjusted to 98.901 (notional 197.802, fee 0.098901): cash
1000 - 202.202 - 0.101101 + 197.802 - 0.098901 = 995.399998, one
losing round trip, net return -0.004600002. The engine's own identity
agrees: 1000 - 4.4 (realised) - 0.200002 (fees) = 995.399998.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

import pytest

from harsh_quant_os.backtesting import (
    ENDING_EQUITY,
    AccessLedger,
    BacktestData,
    BacktestError,
    BacktestResult,
    Candidate,
    CandidateRun,
    DataSplit,
    DecisionContext,
    SelectionObjective,
    SelectionTrace,
    compute_run_id,
    evaluate_held_out,
    select_on_train,
    train_test_split,
)
from tests.backtesting.test_engine import ApproveAll, Threshold, _bar, _config, _data

pytestmark = pytest.mark.backtesting


class HoldAll:
    """Never trades — the do-nothing candidate."""

    name = "hold"

    def decide(self, context: DecisionContext) -> Decimal | None:
        return Decimal(0)

    def describe(self) -> Mapping[str, str]:
        return {"rule": "always flat"}


class BuyAll:
    """Always targets two units — the always-in candidate."""

    name = "buy"

    def decide(self, context: DecisionContext) -> Decimal | None:
        return Decimal(2)

    def describe(self) -> Mapping[str, str]:
        return {"rule": "always 2"}


_HOLD = Candidate(label="hold", build=HoldAll)
_BUY = Candidate(label="buy", build=BuyAll)


def _split(
    test_bars: int = 3,
) -> tuple[BacktestData, BacktestData, DataSplit]:
    return train_test_split(_data(), test_bars=test_bars)


# ---------------------------------------------------------------------------
# The cut
# ---------------------------------------------------------------------------


def test_the_cut_is_chronological_and_the_slices_stay_pinned() -> None:
    data = _data()
    train, held_out, split = _split(test_bars=2)

    assert split.dataset_id == data.dataset_id
    assert split.dataset_version == data.version
    assert split.train_bars == 3 and split.test_bars == 2
    assert split.train_start == data.bars[0].timestamp
    assert split.train_end == data.bars[2].timestamp
    assert split.test_start == data.bars[3].timestamp
    assert split.test_end == data.bars[4].timestamp
    # The held-out suffix is strictly later — no shuffle, no overlap.
    assert split.train_end < split.test_start
    # Slices are the same artefact, cut: same pin, contiguous bars.
    assert train.version == data.version and held_out.version == data.version
    assert train.bars + held_out.bars == data.bars


def test_an_impossible_cut_is_refused() -> None:
    for bad in (-1, 0, 5, 6):
        with pytest.raises(BacktestError, match="at least one training bar"):
            train_test_split(_data(), test_bars=bad)


def test_a_split_that_overlaps_or_runs_backwards_is_refused() -> None:
    version = _data().version
    # Training span t3..t4 with a held-out span at t0..t1: overlap.
    with pytest.raises(BacktestError, match="strictly after every training bar"):
        DataSplit(
            dataset_id="test.bars",
            dataset_version=version,
            train_start=_bar(3, "101", "100").timestamp,
            train_end=_bar(4, "99", "98").timestamp,
            test_start=_bar(0, "100", "100").timestamp,
            test_end=_bar(1, "102", "104").timestamp,
            train_bars=2,
            test_bars=2,
        )
    # Training span running backwards.
    with pytest.raises(BacktestError, match="runs backwards"):
        DataSplit(
            dataset_id="test.bars",
            dataset_version=version,
            train_start=_bar(4, "99", "98").timestamp,
            train_end=_bar(3, "101", "100").timestamp,
            test_start=_bar(0, "100", "100").timestamp,
            test_end=_bar(1, "102", "104").timestamp,
            train_bars=2,
            test_bars=2,
        )
    # An empty side.
    with pytest.raises(BacktestError, match="at least one bar on each side"):
        DataSplit(
            dataset_id="test.bars",
            dataset_version=version,
            train_start=_bar(0, "100", "100").timestamp,
            train_end=_bar(0, "100", "100").timestamp,
            test_start=_bar(1, "102", "104").timestamp,
            test_end=_bar(1, "102", "104").timestamp,
            train_bars=1,
            test_bars=0,
        )


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------


def test_a_second_held_out_touch_is_refused_not_logged() -> None:
    _, _, split = _split()
    original = AccessLedger()
    after_train = original.record_split(
        slice_name="train", purpose="candidate selection", split=split
    )
    after_first = after_train.record_split(
        slice_name="held-out", purpose="held-out evaluation", split=split
    )

    # Append-only: recording returned new ledgers, editing none.
    assert original.entries == ()
    assert len(after_train.entries) == 1
    assert after_first.held_out_touches == 1

    with pytest.raises(BacktestError, match="touches it once"):
        after_first.record_split(slice_name="held-out", purpose="peek again", split=split)
    # The refused touch is not on the ledger — it never happened.
    assert after_first.held_out_touches == 1


def test_an_unknown_slice_cannot_be_recorded() -> None:
    _, _, split = _split()
    with pytest.raises(BacktestError, match="unknown slice"):
        AccessLedger().record_split(slice_name="validation", purpose="something", split=split)


# ---------------------------------------------------------------------------
# The held-out evaluation
# ---------------------------------------------------------------------------


def test_the_held_out_evaluation_runs_once_with_hand_computed_numbers() -> None:
    _train, held_out, split = _split(test_bars=3)
    ledger = AccessLedger().record_split(
        slice_name="train", purpose="candidate selection", split=split
    )

    evaluation = evaluate_held_out(
        held_out,
        split=split,
        strategy=Threshold(),
        config=_config(),
        risk=ApproveAll(),
        ledger=ledger,
    )

    numbers = evaluation.numbers
    # Hand-traced above: entry 101.101, exit 98.901, two fees, flat.
    assert numbers.ending_equity == Decimal("995.399998")
    assert numbers.net_return == Decimal("-0.004600002")
    assert numbers.filled == 2
    assert numbers.round_trips == 1
    assert numbers.wins == 0 and numbers.losses == 1 and numbers.breakeven == 0
    assert numbers.commission == Decimal("0.200002")
    assert numbers.open_at_end is False

    # The manifest is the evidence: self-consistent and about this slice.
    assert evaluation.manifest["run_id"] == compute_run_id(evaluation.manifest)
    recorded = evaluation.manifest["dataset"]
    assert isinstance(recorded, dict)
    assert recorded["start"] == held_out.bars[0].timestamp.isoformat()
    assert recorded["end"] == held_out.bars[-1].timestamp.isoformat()

    # Exactly one held-out touch recorded, after the run succeeded.
    assert evaluation.ledger.held_out_touches == 1
    assert evaluation.ledger.entries[1].slice_name == "held-out"
    assert evaluation.ledger.entries[1].purpose == "held-out evaluation"

    # A second evaluation on the same ledger is refused before the
    # strategy sees a single bar.
    with pytest.raises(BacktestError, match="touches it once"):
        evaluate_held_out(
            held_out,
            split=split,
            strategy=Threshold(),
            config=_config(),
            risk=ApproveAll(),
            ledger=evaluation.ledger,
        )


def test_data_that_is_not_the_split_s_slice_is_refused() -> None:
    train, held_out, split = _split(test_bars=3)

    # The training slice wearing a held-out label.
    with pytest.raises(BacktestError, match="not the held-out slice"):
        evaluate_held_out(
            train,
            split=split,
            strategy=Threshold(),
            config=_config(),
            risk=ApproveAll(),
            ledger=AccessLedger(),
        )

    # The whole dataset instead of the suffix.
    with pytest.raises(BacktestError, match="not the held-out slice"):
        evaluate_held_out(
            _data(),
            split=split,
            strategy=Threshold(),
            config=_config(),
            risk=ApproveAll(),
            ledger=AccessLedger(),
        )

    # Same bars, different dataset id — not this split's artefact.
    impostor = BacktestData(dataset_id="other.bars", version=held_out.version, bars=held_out.bars)
    with pytest.raises(BacktestError, match="not the split's pinned artefact"):
        evaluate_held_out(
            impostor,
            split=split,
            strategy=Threshold(),
            config=_config(),
            risk=ApproveAll(),
            ledger=AccessLedger(),
        )


# ---------------------------------------------------------------------------
# Selection on the training slice
# ---------------------------------------------------------------------------


def test_selection_ranks_by_the_objective_and_records_every_variant() -> None:
    data = _data()
    train = data.span(0, 2)

    trace = select_on_train(
        train,
        candidates=[_HOLD, _BUY],
        config=_config(commission_bps="0", slippage_bps="0"),
        risk_factory=ApproveAll,
    )

    # Hand-traced on zero costs: buy fills t1 open 102 (cash 796) and
    # marks at 104 -> 1004; hold stays at 1000.
    assert trace.selected == "buy"
    assert trace.tied == ("buy",)
    assert trace.objective == ENDING_EQUITY.name
    assert [run.label for run in trace.runs] == ["hold", "buy"]
    assert [run.score for run in trace.runs] == [Decimal(1000), Decimal(1004)]

    for run in trace.runs:
        assert run.manifest["run_id"] == compute_run_id(run.manifest)
        recorded = run.manifest["dataset"]
        assert isinstance(recorded, dict)
        assert recorded["start"] == train.bars[0].timestamp.isoformat()
        assert recorded["end"] == train.bars[-1].timestamp.isoformat()


def test_a_tie_is_recorded_not_hidden() -> None:
    train = _data().span(0, 2)

    trace = select_on_train(
        train,
        candidates=[
            Candidate(label="hold", build=HoldAll),
            Candidate(label="hold-again", build=HoldAll),
        ],
        config=_config(commission_bps="0", slippage_bps="0"),
        risk_factory=ApproveAll,
    )

    # Both never trade -> both 1000: the first declared wins, and the
    # tie itself is on the record.
    assert trace.selected == "hold"
    assert trace.tied == ("hold", "hold-again")
    assert [run.score for run in trace.runs] == [Decimal(1000), Decimal(1000)]


def test_the_objective_decides_the_winner_and_names_itself() -> None:
    train = _data().span(0, 2)
    candidates = [_HOLD, _BUY]

    # Highest ending equity picks the trader; fewest fills picks the
    # do-nothing candidate from the identical runs.
    by_equity = select_on_train(
        train,
        candidates=candidates,
        config=_config(commission_bps="0", slippage_bps="0"),
        risk_factory=ApproveAll,
    )
    by_fills = select_on_train(
        train,
        candidates=candidates,
        config=_config(commission_bps="0", slippage_bps="0"),
        risk_factory=ApproveAll,
        objective=SelectionObjective(
            name="fewest_fills", score=lambda result: -Decimal(len(result.filled))
        ),
    )

    assert by_equity.selected == "buy"
    assert by_equity.objective == "ending_equity"
    assert by_fills.selected == "hold"
    assert by_fills.objective == "fewest_fills"
    assert [run.score for run in by_fills.runs] == [Decimal(0), Decimal(-1)]

    with pytest.raises(BacktestError, match="must name itself"):
        SelectionObjective(name="   ", score=lambda result: result.ending_equity)


def test_an_objective_that_cannot_rank_is_refused() -> None:
    train = _data().span(0, 2)
    candidates = [_HOLD, _BUY]

    def returns_float(result: BacktestResult) -> Decimal:
        return 1.0  # type: ignore[return-value]

    with pytest.raises(BacktestError, match="finite Decimal"):
        select_on_train(
            train,
            candidates=candidates,
            config=_config(),
            risk_factory=ApproveAll,
            objective=SelectionObjective(name="floaty", score=returns_float),
        )

    with pytest.raises(BacktestError, match="finite Decimal"):
        select_on_train(
            train,
            candidates=candidates,
            config=_config(),
            risk_factory=ApproveAll,
            objective=SelectionObjective(name="nan", score=lambda r: Decimal("NaN")),
        )


def test_selection_refusals_are_explicit() -> None:
    train = _data().span(0, 2)

    with pytest.raises(BacktestError, match="at least one candidate"):
        select_on_train(train, candidates=[], config=_config(), risk_factory=ApproveAll)

    with pytest.raises(BacktestError, match="needs a label"):
        Candidate(label="", build=HoldAll)
    with pytest.raises(BacktestError, match="needs a label"):
        Candidate(label="   ", build=HoldAll)


def test_candidates_are_built_fresh_for_every_run() -> None:
    builds = {"count": 0}

    def build() -> HoldAll:
        builds["count"] += 1
        return HoldAll()

    train = _data().span(0, 2)
    select_on_train(
        train,
        candidates=[Candidate(label="hold", build=build)],
        config=_config(),
        risk_factory=ApproveAll,
    )

    assert builds["count"] == 1


# ---------------------------------------------------------------------------
# Trace integrity (the record checks itself)
# ---------------------------------------------------------------------------


def _run(label: str, score: str) -> CandidateRun:
    return CandidateRun(label=label, score=Decimal(score), manifest={})


def test_a_trace_that_cannot_be_true_is_refused() -> None:
    with pytest.raises(BacktestError, match="at least one run"):
        SelectionTrace(selected="a", tied=("a",), objective="o", runs=())

    with pytest.raises(BacktestError, match="duplicate candidate labels"):
        SelectionTrace(
            selected="a",
            tied=("a",),
            objective="o",
            runs=(_run("a", "1"), _run("a", "2")),
        )

    with pytest.raises(BacktestError, match="not among the runs"):
        SelectionTrace(selected="ghost", tied=("ghost",), objective="o", runs=(_run("a", "1"),))

    with pytest.raises(BacktestError, match="not the top score"):
        SelectionTrace(
            selected="a",
            tied=("a",),
            objective="o",
            runs=(_run("a", "1"), _run("b", "2")),
        )

    with pytest.raises(BacktestError, match="does not match the scores"):
        SelectionTrace(
            selected="a",
            tied=("a",),
            objective="o",
            runs=(_run("a", "1"), _run("b", "1")),
        )
