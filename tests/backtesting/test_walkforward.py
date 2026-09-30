"""Walk-forward contract: windows, per-window selection, the stored evidence.

Golden trace, hand-computed on the golden bars at zero costs
(``_config(commission_bps="0", slippage_bps="0")``), layout
train=2 / test=2 / step=1 over the five golden bars:

- Window 0: train [t0, t1] — hold stays 1000, buy fills t1 open 102
  (cash 796) and marks at 104 -> 1004, so **buy** is selected; the
  test [t2, t3] runs buy: decide t2 (close 103), fill t3 open 101
  (cash 798), mark at 100 -> ending 998, net return -0.002, position
  still open at the end.
- Window 1: train [t1, t2] — hold 1000, buy fills t2 open 105 (cash
  790) and marks at 103 -> 996, so **hold** is selected; the test
  [t3, t4] runs hold: no orders, ending 1000, net return 0.

Track: compounded (0.998 * 1) - 1 = -0.002; 0 positive, 1 negative,
1 flat; best window 1, worst window 0; 1 filled order; no completed
round trips, so hit rate and Wilson interval are ``None``; one window
ends holding; 2 candidates x 2 windows = 4 variants tried.

A single-candidate run (threshold, train=2 / test=3) supplies the
completed round trip: test [t2, t3, t4] decides at t2's close 103,
fills t3 open 101, exits on t3's close 100 filling t4 open 99 ->
cash 996, net -0.004, one losing trip, hit rate 0/1 with a Wilson
interval from ``wilson_interval(0, 1)``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any

import pytest

from harsh_quant_os.backtesting import (
    BacktestError,
    Candidate,
    DecisionContext,
    WalkForwardSummary,
    WindowOutcome,
    compute_run_id,
    walk_forward,
    walk_forward_windows,
    wilson_interval,
)
from tests.backtesting.test_engine import ApproveAll, Threshold, _config, _data

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


def _walk(
    *,
    candidates: Sequence[Candidate] | None = None,
    train: int = 2,
    test: int = 2,
) -> WalkForwardSummary:
    """The golden walk-forward: two candidates, zero costs, step one."""
    return walk_forward(
        _data(),
        candidates=[_HOLD, _BUY] if candidates is None else candidates,
        config=_config(commission_bps="0", slippage_bps="0"),
        risk_factory=ApproveAll,
        train=train,
        test=test,
        step=1,
    )


# ---------------------------------------------------------------------------
# Window generation
# ---------------------------------------------------------------------------


def test_windows_are_adjacent_and_strictly_ordered() -> None:
    data = _data()
    windows = walk_forward_windows(data, train=2, test=2, step=1)

    assert len(windows) == 2
    first, second = windows
    assert (first.index, first.train_index, first.train_bars) == (0, 0, 2)
    assert first.train_start == data.bars[0].timestamp
    assert first.train_end == data.bars[1].timestamp
    assert (first.test_index, first.test_bars) == (2, 2)
    assert first.test_start == data.bars[2].timestamp
    assert first.test_end == data.bars[3].timestamp
    # The test slice starts exactly where its own training ends.
    assert first.test_index == first.train_index + first.train_bars
    assert first.train_end < first.test_start

    assert (second.index, second.train_index, second.train_bars) == (1, 1, 2)
    assert second.train_start == data.bars[1].timestamp
    assert (second.test_index, second.test_bars) == (3, 2)
    assert second.test_end == data.bars[4].timestamp
    # Windows advance by the step.
    assert second.train_index - first.train_index == 1


def test_expanding_windows_grow_from_the_first_bar() -> None:
    data = _data()
    windows = walk_forward_windows(data, train=2, test=2, step=1, expanding=True)

    assert len(windows) == 2
    first, second = windows
    assert (first.train_index, first.train_bars) == (0, 2)
    assert (second.train_index, second.train_bars) == (0, 3)
    assert second.train_start == data.bars[0].timestamp
    assert second.train_end == data.bars[2].timestamp
    # Test slices keep advancing the same way as the rolling layout.
    assert [window.test_index for window in windows] == [2, 3]


def test_step_widens_the_stride() -> None:
    windows = walk_forward_windows(_data(), train=2, test=2, step=2)
    assert [window.train_index for window in windows] == [0]
    assert windows[0].test_index == 2


def test_a_layout_with_no_window_is_refused() -> None:
    with pytest.raises(BacktestError, match="no walk-forward window fits"):
        walk_forward_windows(_data(), train=4, test=4, step=1)
    with pytest.raises(BacktestError, match="positive bar counts"):
        walk_forward_windows(_data(), train=0, test=2, step=1)
    with pytest.raises(BacktestError, match="positive bar counts"):
        walk_forward_windows(_data(), train=2, test=2, step=0)


# ---------------------------------------------------------------------------
# The golden walk-forward
# ---------------------------------------------------------------------------


def test_walk_forward_selects_per_window_and_tests_after_it() -> None:
    data = _data()
    summary = _walk()

    assert summary.dataset_id == data.dataset_id
    assert summary.dataset_version == data.version
    assert (summary.train_bars, summary.test_bars, summary.step_bars) == (2, 2, 1)
    assert summary.expanding is False
    assert summary.objective == "ending_equity"
    assert summary.candidates == ("hold", "buy")
    assert len(summary.outcomes) == 2

    window0, window1 = summary.outcomes

    # Window 0 selected the trader on hand-computed scores.
    assert [run.score for run in window0.selection.runs] == [
        Decimal(1000),
        Decimal(1004),
    ]
    assert window0.selection.selected == "buy"
    assert window0.selection.tied == ("buy",)
    # ... and its test segment ran buy: -0.002, still long at the end.
    assert window0.out_of_sample.net_return == Decimal("-0.002")
    assert window0.out_of_sample.ending_equity == Decimal(998)
    assert window0.out_of_sample.filled == 1
    assert window0.out_of_sample.round_trips == 0
    assert window0.out_of_sample.open_at_end is True
    assert window0.out_of_sample.commission == Decimal(0)

    # Window 1 selected do-nothing (buy would have lost on the train).
    assert [run.score for run in window1.selection.runs] == [
        Decimal(1000),
        Decimal(996),
    ]
    assert window1.selection.selected == "hold"
    assert window1.out_of_sample.net_return == Decimal(0)
    assert window1.out_of_sample.ending_equity == Decimal(1000)
    assert window1.out_of_sample.filled == 0
    assert window1.out_of_sample.open_at_end is False


def test_the_aggregate_track_is_the_documented_compounding() -> None:
    track = _walk().track

    assert track.windows == 2
    assert track.compounded_net_return == Decimal("-0.002")
    assert (track.positive, track.negative, track.flat) == (0, 1, 1)
    assert (track.best_window, track.best_return) == (1, Decimal(0))
    assert (track.worst_window, track.worst_return) == (0, Decimal("-0.002"))
    assert track.filled == 1
    assert track.commission == Decimal(0)
    # No completed round trips: nothing to hit, no interval — None,
    # never a plausible-looking zero.
    assert (track.round_trips, track.wins, track.losses, track.breakeven) == (0, 0, 0, 0)
    assert track.hit_rate is None
    assert track.wilson_low is None and track.wilson_high is None
    assert track.open_at_end_windows == 1
    assert track.variants_tried == 4


def test_every_run_carries_a_manifest_that_agrees_with_itself() -> None:
    data = _data()
    summary = _walk()

    for outcome in summary.outcomes:
        window = outcome.window
        for run in outcome.selection.runs:
            assert run.manifest["run_id"] == compute_run_id(run.manifest)
            recorded = run.manifest["dataset"]
            assert isinstance(recorded, dict)
            assert recorded["start"] == data.bars[window.train_index].timestamp.isoformat()
            assert recorded["end"] == data.bars[window.test_index - 1].timestamp.isoformat()
        assert outcome.manifest["run_id"] == compute_run_id(outcome.manifest)
        recorded = outcome.manifest["dataset"]
        assert isinstance(recorded, dict)
        assert recorded["start"] == data.bars[window.test_index].timestamp.isoformat()
        assert recorded["end"] == (
            data.bars[window.test_index + window.test_bars - 1].timestamp.isoformat()
        )


def test_pooled_round_trips_produce_a_hit_rate_and_interval() -> None:
    # Single candidate, train=2 / test=3: the test segment completes
    # one losing round trip (enter 101, exit 99, zero costs).
    summary = _walk(
        candidates=[Candidate(label="threshold", build=Threshold)],
        train=2,
        test=3,
    )

    assert len(summary.outcomes) == 1
    outcome = summary.outcomes[0]
    assert outcome.selection.selected == "threshold"
    assert outcome.out_of_sample.ending_equity == Decimal(996)
    assert outcome.out_of_sample.net_return == Decimal("-0.004")
    assert outcome.out_of_sample.filled == 2
    assert outcome.out_of_sample.round_trips == 1
    assert outcome.out_of_sample.wins == 0
    assert outcome.out_of_sample.losses == 1
    assert outcome.out_of_sample.open_at_end is False

    track = summary.track
    assert track.compounded_net_return == Decimal("-0.004")
    assert (track.positive, track.negative, track.flat) == (0, 1, 0)
    assert (track.best_window, track.worst_window) == (0, 0)
    assert track.hit_rate == Decimal(0)
    interval = wilson_interval(0, 1)
    assert interval is not None
    assert track.wilson_low == interval[0]
    assert track.wilson_high == interval[1]
    assert track.variants_tried == 1


def test_two_identical_runs_produce_identical_json() -> None:
    assert _walk().to_json() == _walk().to_json()


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_walk_forward_refusals_are_explicit() -> None:
    with pytest.raises(BacktestError, match="at least one candidate"):
        _walk(candidates=[])
    with pytest.raises(BacktestError, match="must be distinct"):
        _walk(candidates=[_HOLD, Candidate(label="hold", build=HoldAll)])
    with pytest.raises(BacktestError, match="no walk-forward window fits"):
        _walk(train=4, test=4)


def test_a_summary_that_cannot_be_true_is_refused() -> None:
    summary = _walk()
    with pytest.raises(BacktestError, match="at least one window"):
        WalkForwardSummary(
            dataset_id=summary.dataset_id,
            dataset_version=summary.dataset_version,
            train_bars=2,
            test_bars=2,
            step_bars=1,
            expanding=False,
            objective="ending_equity",
            candidates=("hold", "buy"),
            outcomes=(),
        )

    # A summary declaring candidates the window traces did not race.
    outcome = summary.outcomes[0]
    broken = WindowOutcome(
        window=outcome.window,
        selection=outcome.selection,  # raced hold, buy
        out_of_sample=outcome.out_of_sample,
        manifest=outcome.manifest,
    )
    with pytest.raises(BacktestError, match="must race the same"):
        WalkForwardSummary(
            dataset_id=summary.dataset_id,
            dataset_version=summary.dataset_version,
            train_bars=2,
            test_bars=2,
            step_bars=1,
            expanding=False,
            objective="ending_equity",
            candidates=("hold", "buy-something-else"),
            outcomes=(broken,),
        )

    # A summary recording an objective its traces never used.
    with pytest.raises(BacktestError, match="ranked under"):
        WalkForwardSummary(
            dataset_id=summary.dataset_id,
            dataset_version=summary.dataset_version,
            train_bars=2,
            test_bars=2,
            step_bars=1,
            expanding=False,
            objective="fewest_fills",
            candidates=summary.candidates,
            outcomes=summary.outcomes,
        )


# ---------------------------------------------------------------------------
# Stored evidence
# ---------------------------------------------------------------------------


def _tampered(text: str, mutate: Callable[[Any], None]) -> str:
    """Re-serialise stored JSON after an edit (the canonical form)."""
    payload: Any = json.loads(text)
    mutate(payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _break_track(payload: Any) -> None:
    payload["out_of_sample_track"]["compounded_net_return"] = "0.5"


def _break_manifest(payload: Any) -> None:
    payload["windows"][0]["selection"]["train_runs"][0]["manifest"]["capital"] = "999"


def _break_kind(payload: Any) -> None:
    payload["kind"] = "something_else"


def _break_version(payload: Any) -> None:
    payload["summary_version"] = 99


def _break_notes(payload: Any) -> None:
    payload["notes"][0] = "edited away"


def test_the_summary_survives_a_json_round_trip() -> None:
    summary = _walk()
    text = summary.to_json()
    reloaded = WalkForwardSummary.from_json(text)

    assert reloaded.to_json() == text
    assert reloaded.dataset_version == summary.dataset_version
    assert reloaded.candidates == summary.candidates
    assert len(reloaded.outcomes) == len(summary.outcomes)
    assert [o.selection.selected for o in reloaded.outcomes] == [
        o.selection.selected for o in summary.outcomes
    ]
    assert reloaded.track == summary.track
    assert reloaded.track.compounded_net_return == Decimal("-0.002")
    # Full structural equality: manifests included.
    assert reloaded == summary


def test_a_tampered_summary_is_refused() -> None:
    text = _walk().to_json()

    # An aggregate that does not follow from its windows.
    with pytest.raises(BacktestError, match="does not match the windows"):
        WalkForwardSummary.from_json(_tampered(text, _break_track))

    # A manifest whose payload no longer hashes to its recorded run_id.
    with pytest.raises(BacktestError, match="run_id does not match"):
        WalkForwardSummary.from_json(_tampered(text, _break_manifest))

    # Someone else's document.
    with pytest.raises(BacktestError, match="not a walk-forward summary"):
        WalkForwardSummary.from_json(_tampered(text, _break_kind))

    # A layout this build does not understand.
    with pytest.raises(BacktestError, match="not what this build understands"):
        WalkForwardSummary.from_json(_tampered(text, _break_version))

    # Edited honesty notes.
    with pytest.raises(BacktestError, match="honesty notes"):
        WalkForwardSummary.from_json(_tampered(text, _break_notes))

    # Not JSON at all.
    with pytest.raises(BacktestError, match="not valid JSON"):
        WalkForwardSummary.from_json("{not json")
