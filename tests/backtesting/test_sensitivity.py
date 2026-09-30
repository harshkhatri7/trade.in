"""Parameter sensitivity: every declared cell, and the surface it forms.

Golden trace, hand-computed on the golden bars at zero costs
(``_config(commission_bps="0", slippage_bps="0")``, capital 1000),
axes ``threshold = (100, 105)`` x ``target = (2, 3)`` in declared
order (last axis varies fastest):

- (100, 2): decide t1 (close 104), fill t2 open 105 (cash 790),
  mark 103, hold through t3 (close 100 is not > 100), exit t4 open
  99 (cash 988) -> ending 988, net -0.012, 2 fills, one losing trip.
- (100, 3): the same shape times 3/2: cash 685 after the entry,
  982 after the exit -> ending 982, net -0.018, one losing trip.
- (105, 2) and (105, 3): no close exceeds 105, so neither trades:
  ending 1000, net 0, 0 fills.

Scores (ending equity): 988, 982, 1000, 1000 -> best cell 2, tied
with cell 3; range 982..1000; signs (-, -, 0, 0) -> 0 positive,
2 negative, 2 flat. Adjacency: threshold pairs (0,2) and (1,3),
target pairs (0,1) and (2,3) -> 4 pairs, of which the two
same-sign pairs ((0,1) both negative, (2,3) both flat) agree.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from harsh_quant_os.backtesting import (
    BacktestError,
    DecisionContext,
    OutOfSampleNumbers,
    SelectionObjective,
    SensitivitySurface,
    compute_run_id,
    load_backtest_data,
    parameter_sensitivity,
    replay_sensitivity,
)
from tests.backtesting.test_engine import ApproveAll, _config, _data
from tests.backtesting.test_manifest import GOLDEN_ROWS
from tests.quant.test_recipes import _csv_bytes, _write_store

pytestmark = pytest.mark.backtesting

_AXES: dict[str, tuple[str, ...]] = {
    "threshold": ("100", "105"),
    "target": ("2", "3"),
}


class Sweep:
    """The threshold rule, parameterised exactly as the grid declares it."""

    def __init__(self, threshold: str, target: str) -> None:
        self.threshold = Decimal(threshold)
        self.target = Decimal(target)
        self.name = "sweep"

    def decide(self, context: DecisionContext) -> Decimal | None:
        return self.target if context.bar.close > self.threshold else Decimal(0)

    def describe(self) -> Mapping[str, str]:
        return {"entry": f"close > {self.threshold}", "target_qty": str(self.target)}


def _build(parameters: Mapping[str, str]) -> Sweep:
    return Sweep(threshold=parameters["threshold"], target=parameters["target"])


def _surface() -> SensitivitySurface:
    """The golden sweep: two axes, four cells, zero costs, in memory."""
    return parameter_sensitivity(
        _data(),
        axes=_AXES,
        build=_build,
        config=_config(commission_bps="0", slippage_bps="0"),
        risk_factory=ApproveAll,
    )


def _stored_surface(tmp_path: Path) -> SensitivitySurface:
    """The same sweep over the golden bars *as stored* (for replay)."""
    _write_store(tmp_path, "test.bars", _csv_bytes(GOLDEN_ROWS))
    data = load_backtest_data(tmp_path, "test.bars")
    return parameter_sensitivity(
        data,
        axes=_AXES,
        build=_build,
        config=_config(commission_bps="0", slippage_bps="0"),
        risk_factory=ApproveAll,
    )


# ---------------------------------------------------------------------------
# The surface
# ---------------------------------------------------------------------------


def test_the_surface_records_every_declared_cell() -> None:
    data = _data()
    surface = _surface()

    assert surface.dataset_id == data.dataset_id
    assert surface.dataset_version == data.version
    assert surface.objective == "ending_equity"
    assert surface.axes == (("threshold", ("100", "105")), ("target", ("2", "3")))
    assert [cell.parameters for cell in surface.cells] == [
        (("threshold", "100"), ("target", "2")),
        (("threshold", "100"), ("target", "3")),
        (("threshold", "105"), ("target", "2")),
        (("threshold", "105"), ("target", "3")),
    ]

    # Hand-traced above: the trader loses, the bigger trader loses
    # more, the too-high threshold never trades.
    assert [cell.score for cell in surface.cells] == [
        Decimal(988),
        Decimal(982),
        Decimal(1000),
        Decimal(1000),
    ]
    assert [cell.numbers.net_return for cell in surface.cells] == [
        Decimal("-0.012"),
        Decimal("-0.018"),
        Decimal(0),
        Decimal(0),
    ]
    assert [cell.numbers.filled for cell in surface.cells] == [2, 2, 0, 0]
    assert [cell.numbers.round_trips for cell in surface.cells] == [1, 1, 0, 0]

    # Every cell is a full run over the same pinned slice, with a
    # manifest that agrees with itself.
    for cell in surface.cells:
        record = cell.manifest["dataset"]
        assert isinstance(record, dict)
        assert record["start"] == data.start.isoformat()
        assert record["end"] == data.end.isoformat()
        assert cell.manifest["run_id"] == compute_run_id(cell.manifest)


def test_the_best_cell_is_reported_beside_the_surface() -> None:
    surface = _surface()

    assert surface.configurations_tried == 4
    assert surface.best == 2
    assert surface.best_tied == (2, 3)
    assert (surface.score_min, surface.score_max) == (Decimal(982), Decimal(1000))
    assert (surface.positive, surface.negative, surface.flat) == (0, 2, 2)
    # Threshold pairs (0, 2) and (1, 3) disagree in sign; target pairs
    # (0, 1) are both negative and (2, 3) are both flat.
    assert (surface.adjacent_pairs, surface.adjacent_agreeing) == (4, 2)


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_grid_that_is_not_a_sweep_is_refused() -> None:
    def run(axes: Mapping[str, Sequence[str]]) -> None:
        parameter_sensitivity(
            _data(),
            axes=axes,
            build=_build,
            config=_config(commission_bps="0", slippage_bps="0"),
            risk_factory=ApproveAll,
        )

    with pytest.raises(BacktestError, match="at least one axis"):
        run({})
    with pytest.raises(BacktestError, match="at least one value"):
        run({"threshold": ()})
    with pytest.raises(BacktestError, match="repeats the value"):
        run({"threshold": ("100", "100")})
    with pytest.raises(BacktestError, match="non-empty strings"):
        run({"threshold": ("",)})
    with pytest.raises(BacktestError, match="must be non-empty"):
        run({"": ("100",)})


def test_two_cells_that_are_the_same_run_are_refused() -> None:
    # The builder ignores the target axis, so each threshold becomes
    # two identical runs: the declared variation never reaches the run.
    def blind(parameters: Mapping[str, str]) -> Sweep:
        return Sweep(threshold=parameters["threshold"], target="2")

    with pytest.raises(BacktestError, match="identical manifest"):
        parameter_sensitivity(
            _data(),
            axes=_AXES,
            build=blind,
            config=_config(commission_bps="0", slippage_bps="0"),
            risk_factory=ApproveAll,
        )


def test_a_surface_that_cannot_be_true_is_refused() -> None:
    surface = _surface()

    # The grid's order is its identity: it cannot be rearranged.
    with pytest.raises(BacktestError, match="declared grid places"):
        replace(surface, cells=tuple(reversed(surface.cells)))
    # The cell count is the multiple-testing denominator.
    with pytest.raises(BacktestError, match="declare 4 configurations"):
        replace(surface, cells=surface.cells[:2])
    with pytest.raises(BacktestError, match="at least one cell"):
        replace(surface, cells=())
    # One surface sweeps one pinned dataset and one slice.
    with pytest.raises(BacktestError, match="one pinned dataset"):
        replace(surface, dataset_id="other.bars")
    with pytest.raises(BacktestError, match="disagrees with the slice"):
        replace(surface, slice_end=surface.slice_end + timedelta(hours=1))


# ---------------------------------------------------------------------------
# Stored evidence
# ---------------------------------------------------------------------------


def _tampered(text: str, mutate: Callable[[Any], None]) -> str:
    """Re-serialise stored JSON after an edit (the canonical form)."""
    payload: Any = json.loads(text)
    mutate(payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _break_stat(payload: Any) -> None:
    payload["surface"]["best"] = 0


def _break_numbers(payload: Any) -> None:
    payload["cells"][0]["numbers"]["net_return"] = "0.5"


def _break_run_id(payload: Any) -> None:
    payload["cells"][0]["manifest"]["run_id"] = "0" * 64


def _break_kind(payload: Any) -> None:
    payload["kind"] = "something-else"


def _break_version(payload: Any) -> None:
    payload["sensitivity_version"] = 99


def _break_notes(payload: Any) -> None:
    payload["notes"][0] = "edited away"


def test_the_surface_survives_a_json_round_trip() -> None:
    surface = _surface()
    text = surface.to_json()
    reloaded = SensitivitySurface.from_json(text)

    assert reloaded.to_json() == text
    assert reloaded == surface


def test_a_tampered_surface_is_refused() -> None:
    text = _surface().to_json()

    # Statistics that do not follow from the cells.
    with pytest.raises(BacktestError, match="do not follow from its cells"):
        SensitivitySurface.from_json(_tampered(text, _break_stat))
    with pytest.raises(BacktestError, match="do not follow from its cells"):
        SensitivitySurface.from_json(_tampered(text, _break_numbers))
    # A manifest whose payload no longer hashes to its recorded id.
    with pytest.raises(BacktestError, match="run_id does not match"):
        SensitivitySurface.from_json(_tampered(text, _break_run_id))
    # Someone else's document, or a layout this build cannot read.
    with pytest.raises(BacktestError, match="not a parameter-sensitivity surface"):
        SensitivitySurface.from_json(_tampered(text, _break_kind))
    with pytest.raises(BacktestError, match="not what this build understands"):
        SensitivitySurface.from_json(_tampered(text, _break_version))
    # Edited honesty notes.
    with pytest.raises(BacktestError, match="honesty notes"):
        SensitivitySurface.from_json(_tampered(text, _break_notes))
    # Not JSON at all.
    with pytest.raises(BacktestError, match="not valid JSON"):
        SensitivitySurface.from_json("{not json")


# ---------------------------------------------------------------------------
# Replay: evidence that can be run again
# ---------------------------------------------------------------------------


def test_replay_re_derives_every_cell(tmp_path: Path) -> None:
    surface = _stored_surface(tmp_path)

    results = replay_sensitivity(tmp_path, surface, build=_build, risk_factory=ApproveAll)

    assert len(results) == len(surface.cells)
    for cell, result in zip(surface.cells, results, strict=True):
        assert OutOfSampleNumbers.from_result(result) == cell.numbers
    # The stored JSON form replays too: evidence that survives storage.
    reloaded = SensitivitySurface.from_json(surface.to_json())
    replayed = replay_sensitivity(tmp_path, reloaded, build=_build, risk_factory=ApproveAll)
    assert len(replayed) == 4


def test_replay_refuses_what_it_cannot_re_derive(tmp_path: Path) -> None:
    surface = _stored_surface(tmp_path)

    # The objective the surface scored under.
    different = SelectionObjective(name="fewest_fills", score=lambda result: Decimal(0))
    with pytest.raises(BacktestError, match="cannot be re-derived"):
        replay_sensitivity(
            tmp_path,
            surface,
            build=_build,
            risk_factory=ApproveAll,
            objective=different,
        )

    # A score that does not follow from its manifest.
    falsified = replace(
        surface, cells=(replace(surface.cells[0], score=Decimal(1)), *surface.cells[1:])
    )
    with pytest.raises(BacktestError, match="does not follow from the stored manifest"):
        replay_sensitivity(tmp_path, falsified, build=_build, risk_factory=ApproveAll)

    # Numbers that do not follow from their manifest.
    dreamt = replace(
        surface,
        cells=(
            replace(
                surface.cells[0],
                numbers=replace(surface.cells[0].numbers, net_return=Decimal("0.5")),
            ),
            *surface.cells[1:],
        ),
    )
    with pytest.raises(BacktestError, match="did not reproduce"):
        replay_sensitivity(tmp_path, dreamt, build=_build, risk_factory=ApproveAll)

    # A builder that is not the recorded strategy.
    with pytest.raises(BacktestError, match="does not match the manifest"):
        replay_sensitivity(
            tmp_path,
            surface,
            build=lambda parameters: Sweep(threshold="104", target=parameters["target"]),
            risk_factory=ApproveAll,
        )
