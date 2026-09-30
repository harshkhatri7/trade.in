"""Parameter sensitivity: the surface, not the optimum.

anti-overfitting.md §2.4: a parameter optimiser is a multiple-testing
engine — "Report the surface, not the optimum: a result should include
the full parameter sweep, adjacent-parameter performance, and the
number of configurations tried." experiment-protocol.md §3 requires the
same in every result record.

Design commitments:

- **The grid is declared, not discovered.** Axes (parameter name ->
  ordered distinct values) are given up front; the surface is their
  cartesian product in declared order (last axis varies fastest), so
  the cell count IS the multiple-testing denominator and cannot be
  quietly grown after seeing the data.
- **Values are strings, and they are the evidence.**
  ``strategy.describe()`` maps strings to strings and the manifest
  records exactly those; the sweep hands the declared string to the
  builder and stores it, so what was declared is what the manifest
  carries.
- **Every cell is a full run**: fresh strategy, fresh risk evaluator,
  a §3 manifest, exact-decimal numbers. The best cell is reported
  beside the surface (index and ties), never instead of it.
- **Adjacency is structural**: neighbours differ in exactly one axis
  by one step. Agreement is reported as counts over those pairs, not
  as a score — a spike between two losers is one cell, and the counts
  say so.
- **Evidence checks itself.** Loading a stored surface verifies the
  kind, version, honesty notes, every manifest's ``run_id``, that
  every manifest pins the swept dataset and slice, and that the
  stored statistics follow from the stored cells;
  :func:`replay_sensitivity` goes further and re-executes each cell.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from harsh_quant_os.backtesting.data import BacktestData
from harsh_quant_os.backtesting.engine import BacktestConfig, BacktestResult, run_backtest
from harsh_quant_os.backtesting.errors import BacktestError
from harsh_quant_os.backtesting.manifest import build_manifest, compute_run_id, run_from_manifest
from harsh_quant_os.backtesting.strategy import Strategy
from harsh_quant_os.backtesting.validation import (
    ENDING_EQUITY,
    OutOfSampleNumbers,
    SelectionObjective,
)
from harsh_quant_os.safety.risk import RiskEvaluator

__all__ = [
    "SENSITIVITY_VERSION",
    "SensitivityCell",
    "SensitivitySurface",
    "parameter_sensitivity",
    "replay_sensitivity",
]

#: Bumped when the stored surface layout changes incompatibly.
SENSITIVITY_VERSION = 1

#: What the stored document claims to be.
_KIND = "parameter-sensitivity"

#: The honesty notes every stored surface carries verbatim; a load
#: that finds them edited refuses rather than agreeing to less.
_NOTES = (
    "The surface is the result: every configuration declared is "
    "recorded as one cell, and the best cell is reported beside the "
    "surface, never instead of it.",
    "Cells are the declared cartesian product in declared order; "
    "neighbours differ in exactly one axis by one step, and their "
    "agreement is reported as counts over pairs, not as a score.",
    "Scores and numbers are exact decimals stored beside their "
    "manifests; replay re-executes every cell rather than trusting "
    "the stored arithmetic.",
)


def _sign(value: Decimal) -> int:
    """Sign of an exact number: -1, 0 or 1 (used for neighbour agreement)."""
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


# ---------------------------------------------------------------------------
# One cell of the grid
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SensitivityCell:
    """One configuration of the declared grid, fully run.

    Attributes:
        parameters: ``(axis, value)`` pairs in declared axis order —
            the exact strings the builder received and the manifest
            records.
        score: The objective's value for this run (exact, finite).
        numbers: The run's recorded numbers (net return, ending
            equity, fills, round trips and their split, the
            open-position flag, commission) — the same shape a test
            segment reports, here describing a sweep cell.
        manifest: The run's §3 manifest.

    Raises:
        BacktestError: No pairs, an empty axis name or value, a
            repeated axis, or a non-finite score.
    """

    parameters: tuple[tuple[str, str], ...]
    score: Decimal
    numbers: OutOfSampleNumbers
    manifest: dict[str, object]

    def __post_init__(self) -> None:
        if not self.parameters:
            raise BacktestError("a sensitivity cell records at least one (axis, value) pair")
        seen: set[str] = set()
        for axis, value in self.parameters:
            if not axis or not axis.strip():
                raise BacktestError(f"a cell's axis name must not be empty: {self.parameters!r}")
            if not value:
                raise BacktestError(
                    f"axis {axis!r} must carry a non-empty string value, got {value!r}"
                )
            if axis in seen:
                raise BacktestError(f"cell {self.parameters!r} records axis {axis!r} twice")
            seen.add(axis)
        if not self.score.is_finite():
            raise BacktestError(f"a cell's score must be a finite decimal, got {self.score}")


# ---------------------------------------------------------------------------
# The surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SensitivitySurface:
    """The declared grid with every cell run, and statistics that follow.

    Attributes:
        dataset_id / dataset_version: The one pinned input all cells
            swept.
        slice_start / slice_end: The swept span (first/last bar); each
            cell's manifest must record exactly these bounds.
        objective: The ranking objective's recorded name.
        axes: ``(name, values)`` in declared order (insertion order of
            the mapping the caller passed); cells are their cartesian
            product, last axis varying fastest.
        cells: One per declared configuration, in declared order
            (at least one).

    Raises:
        BacktestError: A surface that cannot be true of its own
            evidence — empty or duplicate axes, a cell count that does
            not follow the declared grid, cell parameters that are not
            the declared assignment for their position, a manifest
            pinning other data or other bounds, or two cells recording
            the identical manifest (the declared variation never
            reached the run).
    """

    dataset_id: str
    dataset_version: str
    slice_start: datetime
    slice_end: datetime
    objective: str
    axes: tuple[tuple[str, tuple[str, ...]], ...]
    cells: tuple[SensitivityCell, ...]

    def __post_init__(self) -> None:
        if not self.dataset_id.strip() or not self.dataset_version:
            raise BacktestError("a sensitivity surface names the dataset it swept")
        for label, value in (("slice start", self.slice_start), ("slice end", self.slice_end)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise BacktestError(f"{label} must be timezone-aware, got {value.isoformat()!r}")
        if self.slice_start > self.slice_end:
            raise BacktestError("the swept slice runs backwards")
        if not self.objective.strip():
            raise BacktestError("a surface records the objective its cells scored under")

        if not self.axes:
            raise BacktestError("a sensitivity surface declares at least one axis")
        axis_names: set[str] = set()
        for name, values in self.axes:
            if not name.strip():
                raise BacktestError("axis names must not be empty")
            if name in axis_names:
                raise BacktestError(f"axis {name!r} is declared twice")
            axis_names.add(name)
            if not values:
                raise BacktestError(f"axis {name!r} declares no values")
            if len(set(values)) != len(values):
                raise BacktestError(
                    f"axis {name!r} repeats a value: the same cell listed twice "
                    "is not a sweep, it is one cell counted twice"
                )

        if not self.cells:
            raise BacktestError("the surface carries at least one cell")
        names = tuple(name for name, _ in self.axes)
        assignments = list(itertools.product(*(values for _, values in self.axes)))
        if len(self.cells) != len(assignments):
            raise BacktestError(
                f"the axes declare {len(assignments)} configurations but the "
                f"surface holds {len(self.cells)} cells: the count is the "
                "multiple-testing denominator and must follow the grid"
            )

        recorded_ids: dict[str, int] = {}
        for index, (cell, assignment) in enumerate(zip(self.cells, assignments, strict=True)):
            expected = tuple(zip(names, assignment, strict=True))
            if cell.parameters != expected:
                raise BacktestError(
                    f"cell {index} records {cell.parameters!r} but the declared "
                    f"grid places {expected!r} there (the surface is the "
                    "declared order, not a re-orderable list)"
                )
            dataset_record = cell.manifest.get("dataset")
            if not isinstance(dataset_record, dict):
                raise BacktestError(f"cell {index}'s manifest carries no dataset record")
            if (
                dataset_record.get("id") != self.dataset_id
                or dataset_record.get("version") != self.dataset_version
            ):
                raise BacktestError(
                    f"cell {index}'s manifest pins {dataset_record.get('id')!r} "
                    f"but the surface sweeps {self.dataset_id!r}: one surface "
                    "sweeps one pinned dataset"
                )
            if (
                dataset_record.get("start") != self.slice_start.isoformat()
                or dataset_record.get("end") != self.slice_end.isoformat()
            ):
                raise BacktestError(
                    f"cell {index}'s manifest records dataset span "
                    f"{dataset_record.get('start')!r} to {dataset_record.get('end')!r} "
                    f"but the sweep spans {self.slice_start.isoformat()} to "
                    f"{self.slice_end.isoformat()}: evidence that disagrees with "
                    "the slice it claims to come from is refused"
                )
            run_id = cell.manifest.get("run_id")
            if not isinstance(run_id, str):
                raise BacktestError(f"cell {index}'s manifest carries no run_id")
            if run_id in recorded_ids:
                raise BacktestError(
                    f"cells {recorded_ids[run_id]} and {index} recorded the "
                    f"identical manifest {run_id}: the declared variation is not "
                    "reaching the run (two cells that are the same run are one "
                    "cell counted twice)"
                )
            recorded_ids[run_id] = index

    # -- statistics: derived, never stored as the source of truth -------

    @property
    def configurations_tried(self) -> int:
        """The multiple-testing denominator: one per declared cell."""
        return len(self.cells)

    @property
    def best_tied(self) -> tuple[int, ...]:
        """Indices holding the top score (first cell on a tie is first)."""
        top = max(cell.score for cell in self.cells)
        return tuple(index for index, cell in enumerate(self.cells) if cell.score == top)

    @property
    def best(self) -> int:
        """Index of the top-scoring cell (first occurrence on ties)."""
        return self.best_tied[0]

    @property
    def positive(self) -> int:
        """Cells whose net return is above zero."""
        return sum(1 for cell in self.cells if cell.numbers.net_return > 0)

    @property
    def negative(self) -> int:
        """Cells whose net return is below zero."""
        return sum(1 for cell in self.cells if cell.numbers.net_return < 0)

    @property
    def flat(self) -> int:
        """Cells whose net return is exactly zero."""
        return sum(1 for cell in self.cells if cell.numbers.net_return == 0)

    @property
    def score_min(self) -> Decimal:
        """Lowest objective value across the surface (exact)."""
        return min(cell.score for cell in self.cells)

    @property
    def score_max(self) -> Decimal:
        """Highest objective value across the surface (exact)."""
        return max(cell.score for cell in self.cells)

    @property
    def adjacent_pairs(self) -> int:
        """Neighbouring cell pairs (differ in one axis by one step)."""
        return self._adjacency()[0]

    @property
    def adjacent_agreeing(self) -> int:
        """Neighbouring pairs whose net returns share a sign."""
        return self._adjacency()[1]

    def _adjacency(self) -> tuple[int, int]:
        """``(adjacent pairs, pairs agreeing in net-return sign)``.

        Strides follow the declared product order (last axis varies
        fastest), so each pair is counted exactly once: cell i with
        cell i + stride only while i is not at that axis's last value.
        """
        lengths = [len(values) for _, values in self.axes]
        strides = [1] * len(lengths)
        running = 1
        for axis in range(len(lengths) - 1, -1, -1):
            strides[axis] = running
            running *= lengths[axis]
        pairs = 0
        agreeing = 0
        for index, cell in enumerate(self.cells):
            for axis, stride in enumerate(strides):
                if (index // stride) % lengths[axis] + 1 >= lengths[axis]:
                    continue  # at this axis's last value: no neighbour beyond
                neighbour = index + stride
                if _sign(cell.numbers.net_return) == _sign(
                    self.cells[neighbour].numbers.net_return
                ):
                    agreeing += 1
                pairs += 1
        return pairs, agreeing

    # -- stored evidence -------------------------------------------------

    def to_json(self) -> str:
        """The surface as canonical JSON (manifest_to_json's byte form)."""
        pairs, agreeing = self._adjacency()
        payload: dict[str, object] = {
            "kind": _KIND,
            "sensitivity_version": SENSITIVITY_VERSION,
            "notes": list(_NOTES),
            "dataset": {"id": self.dataset_id, "version": self.dataset_version},
            "slice": {
                "start": self.slice_start.isoformat(),
                "end": self.slice_end.isoformat(),
            },
            "objective": self.objective,
            "axes": [{"name": name, "values": list(values)} for name, values in self.axes],
            "cells": [
                {
                    "parameters": [[axis, value] for axis, value in cell.parameters],
                    "score": str(cell.score),
                    "numbers": _numbers_payload(cell.numbers),
                    "manifest": cell.manifest,
                }
                for cell in self.cells
            ],
            "surface": {
                "configurations_tried": self.configurations_tried,
                "best": self.best,
                "best_tied": list(self.best_tied),
                "positive": self.positive,
                "negative": self.negative,
                "flat": self.flat,
                "score_min": str(self.score_min),
                "score_max": str(self.score_max),
                "adjacent_pairs": pairs,
                "adjacent_agreeing": agreeing,
            },
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @classmethod
    def from_json(cls, text: str) -> SensitivitySurface:
        """Load a stored surface, refusing anything that does not follow.

        Raises:
            BacktestError: Not JSON, wrong kind or version, edited
                honesty notes, a manifest whose ``run_id`` no longer
                matches its own payload, or statistics that do not
                follow from the stored cells.
        """
        try:
            root = json.loads(text)
        except ValueError as error:
            raise BacktestError(
                f"stored parameter sensitivity is not valid JSON: {error}"
            ) from error
        if not isinstance(root, dict):
            raise BacktestError(
                f"stored parameter sensitivity must be a JSON object, got {type(root).__name__}"
            )
        kind = _as_text(_need(root, "kind", "surface"), "surface.kind")
        if kind != _KIND:
            raise BacktestError(
                f"{kind!r} is not a parameter-sensitivity surface; refusing to "
                "read a document that is not one"
            )
        version = _as_int(
            _need(root, "sensitivity_version", "surface"), "surface.sensitivity_version"
        )
        if version != SENSITIVITY_VERSION:
            raise BacktestError(
                f"sensitivity_version {version} is not what this build understands "
                f"({SENSITIVITY_VERSION}); refusing to guess its layout"
            )
        notes = tuple(
            _as_text(entry, f"surface.notes[{index}]")
            for index, entry in enumerate(
                _as_list(_need(root, "notes", "surface"), "surface.notes")
            )
        )
        if notes != _NOTES:
            raise BacktestError(
                "the surface's honesty notes do not match this build's: the "
                "caveats were edited, so the document is refused rather than "
                "read with fewer of them"
            )

        dataset = _as_mapping(_need(root, "dataset", "surface"), "surface.dataset")
        slice_ = _as_mapping(_need(root, "slice", "surface"), "surface.slice")
        axes: list[tuple[str, tuple[str, ...]]] = []
        for index, entry in enumerate(_as_list(_need(root, "axes", "surface"), "surface.axes")):
            record = _as_mapping(entry, f"surface.axes[{index}]")
            name = _as_text(
                _need(record, "name", f"surface.axes[{index}]"),
                f"surface.axes[{index}].name",
            )
            values = tuple(
                _as_text(value, f"surface.axes[{index}].values[{value_index}]")
                for value_index, value in enumerate(
                    _as_list(
                        _need(record, "values", f"surface.axes[{index}]"),
                        f"surface.axes[{index}].values",
                    )
                )
            )
            axes.append((name, values))

        cells: list[SensitivityCell] = []
        for index, entry in enumerate(_as_list(_need(root, "cells", "surface"), "surface.cells")):
            record = _as_mapping(entry, f"surface.cells[{index}]")
            parameters: list[tuple[str, str]] = []
            for pair_index, pair in enumerate(
                _as_list(
                    _need(record, "parameters", f"surface.cells[{index}]"),
                    f"surface.cells[{index}].parameters",
                )
            ):
                parts = _as_list(pair, f"surface.cells[{index}].parameters[{pair_index}]")
                if len(parts) != 2:
                    raise BacktestError(
                        f"surface.cells[{index}].parameters[{pair_index}] must be "
                        f"[axis, value], got {len(parts)} entries"
                    )
                parameters.append(
                    (
                        _as_text(parts[0], f"surface.cells[{index}].parameters"),
                        _as_text(parts[1], f"surface.cells[{index}].parameters"),
                    )
                )
            cells.append(
                SensitivityCell(
                    parameters=tuple(parameters),
                    score=_as_decimal(
                        _need(record, "score", f"surface.cells[{index}]"),
                        f"surface.cells[{index}].score",
                    ),
                    numbers=_numbers_from(
                        _as_mapping(
                            _need(record, "numbers", f"surface.cells[{index}]"),
                            f"surface.cells[{index}].numbers",
                        ),
                        f"surface.cells[{index}].numbers",
                    ),
                    manifest=_as_mapping(
                        _need(record, "manifest", f"surface.cells[{index}]"),
                        f"surface.cells[{index}].manifest",
                    ),
                )
            )

        surface = cls(
            dataset_id=_as_text(_need(dataset, "id", "surface.dataset"), "surface.dataset.id"),
            dataset_version=_as_text(
                _need(dataset, "version", "surface.dataset"), "surface.dataset.version"
            ),
            slice_start=_as_time(_need(slice_, "start", "surface.slice"), "surface.slice.start"),
            slice_end=_as_time(_need(slice_, "end", "surface.slice"), "surface.slice.end"),
            objective=_as_text(_need(root, "objective", "surface"), "surface.objective"),
            axes=tuple(axes),
            cells=tuple(cells),
        )

        for index, cell in enumerate(surface.cells):
            recorded = cell.manifest.get("run_id")
            derived = compute_run_id(cell.manifest)
            if recorded != derived:
                raise BacktestError(
                    f"cell {index}: manifest run_id does not match its own "
                    f"payload (recorded {recorded!r}, derived {derived!r}) — "
                    "the evidence has been altered since it was written"
                )

        stored = _as_mapping(_need(root, "surface", "surface"), "surface.surface")
        pairs, agreeing = surface._adjacency()
        derived_stats: dict[str, object] = {
            "configurations_tried": surface.configurations_tried,
            "best": surface.best,
            "best_tied": surface.best_tied,
            "positive": surface.positive,
            "negative": surface.negative,
            "flat": surface.flat,
            "score_min": surface.score_min,
            "score_max": surface.score_max,
            "adjacent_pairs": pairs,
            "adjacent_agreeing": agreeing,
        }
        parsers: dict[str, Callable[[object, str], object]] = {
            "configurations_tried": _as_int,
            "best": _as_int,
            "positive": _as_int,
            "negative": _as_int,
            "flat": _as_int,
            "adjacent_pairs": _as_int,
            "adjacent_agreeing": _as_int,
            "score_min": _as_decimal,
            "score_max": _as_decimal,
        }
        for key, expected in derived_stats.items():
            raw = _need(stored, key, "surface.surface")
            if key == "best_tied":
                stored_value: object = tuple(
                    _as_int(entry, f"surface.surface.best_tied[{entry_index}]")
                    for entry_index, entry in enumerate(_as_list(raw, "surface.surface.best_tied"))
                )
            else:
                stored_value = parsers[key](raw, f"surface.surface.{key}")
            if stored_value != expected:
                raise BacktestError(
                    f"the stored surface statistics do not follow from its "
                    f"cells: {key} is {stored_value!r}, the cells say "
                    f"{expected!r}"
                )
        return surface


def _numbers_payload(numbers: OutOfSampleNumbers) -> dict[str, object]:
    return {
        "net_return": str(numbers.net_return),
        "ending_equity": str(numbers.ending_equity),
        "filled": numbers.filled,
        "round_trips": numbers.round_trips,
        "wins": numbers.wins,
        "losses": numbers.losses,
        "breakeven": numbers.breakeven,
        "open_at_end": numbers.open_at_end,
        "commission": str(numbers.commission),
    }


def _numbers_from(record: dict[str, object], where: str) -> OutOfSampleNumbers:
    return OutOfSampleNumbers(
        net_return=_as_decimal(_need(record, "net_return", where), f"{where}.net_return"),
        ending_equity=_as_decimal(_need(record, "ending_equity", where), f"{where}.ending_equity"),
        filled=_as_int(_need(record, "filled", where), f"{where}.filled"),
        round_trips=_as_int(_need(record, "round_trips", where), f"{where}.round_trips"),
        wins=_as_int(_need(record, "wins", where), f"{where}.wins"),
        losses=_as_int(_need(record, "losses", where), f"{where}.losses"),
        breakeven=_as_int(_need(record, "breakeven", where), f"{where}.breakeven"),
        open_at_end=_as_bool(_need(record, "open_at_end", where), f"{where}.open_at_end"),
        commission=_as_decimal(_need(record, "commission", where), f"{where}.commission"),
    )


# ---------------------------------------------------------------------------
# JSON helpers (worded for this document, per module)
# ---------------------------------------------------------------------------


def _need(mapping: dict[str, object], key: str, where: str) -> object:
    if key not in mapping:
        raise BacktestError(f"stored parameter sensitivity is missing {where}.{key}")
    return mapping[key]


def _as_text(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise BacktestError(f"{where} must be a string, got {type(value).__name__}")
    return value


def _as_int(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BacktestError(f"{where} must be an integer, got {type(value).__name__}")
    return value


def _as_bool(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise BacktestError(f"{where} must be true or false, got {type(value).__name__}")
    return value


def _as_decimal(value: object, where: str) -> Decimal:
    text = _as_text(value, where)
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError) as error:
        raise BacktestError(f"{where} is not a decimal number: {text!r}") from error
    if not parsed.is_finite():
        raise BacktestError(f"{where} must be a finite decimal, got {text!r}")
    return parsed


def _as_time(value: object, where: str) -> datetime:
    text = _as_text(value, where)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise BacktestError(f"{where} is not an ISO timestamp: {text!r}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BacktestError(f"{where} must be timezone-aware: {text!r}")
    return parsed


def _as_mapping(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise BacktestError(f"{where} must be a JSON object, got {type(value).__name__}")
    return value


def _as_list(value: object, where: str) -> list[object]:
    if not isinstance(value, list):
        raise BacktestError(f"{where} must be a JSON array, got {type(value).__name__}")
    return value


# ---------------------------------------------------------------------------
# Running the declared grid
# ---------------------------------------------------------------------------


def _check_axes(
    axes: Mapping[str, Sequence[str]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Validate the declared axes, preserving the mapping's own order."""
    if not axes:
        raise BacktestError(
            "a sensitivity surface needs at least one axis: an empty grid is not a sweep"
        )
    checked: list[tuple[str, tuple[str, ...]]] = []
    for name, values in axes.items():
        if not name or not name.strip():
            raise BacktestError(f"axis names must be non-empty, got {name!r}")
        if not values:
            raise BacktestError(
                f"axis {name!r} needs at least one value (a declared axis with "
                "no values declares no sweep)"
            )
        seen: set[str] = set()
        for value in values:
            raw_value: object = value
            if not isinstance(raw_value, str) or not raw_value:
                raise BacktestError(
                    f"axis {name!r} values must be non-empty strings, got {raw_value!r}"
                )
            if raw_value in seen:
                raise BacktestError(
                    f"axis {name!r} repeats the value {raw_value!r}: the same "
                    "cell listed twice is not a sweep, it is one cell counted "
                    "twice"
                )
            seen.add(raw_value)
        checked.append((name, tuple(values)))
    return tuple(checked)


def parameter_sensitivity(
    data: BacktestData,
    *,
    axes: Mapping[str, Sequence[str]],
    build: Callable[[Mapping[str, str]], Strategy],
    config: BacktestConfig,
    risk_factory: Callable[[], RiskEvaluator],
    objective: SelectionObjective = ENDING_EQUITY,
) -> SensitivitySurface:
    """Run the declared grid and return every cell, not just the winner.

    Args:
        data: The pinned dataset every cell sweeps (one slice).
        axes: ``parameter -> ordered distinct values``, read in the
            mapping's own order. The cells are the cartesian product
            (last axis varies fastest). Values are the exact strings
            handed to ``build`` and recorded in the manifests.
        build: Builds a **fresh** strategy from a cell's assignment;
            its ``describe()`` must vary with the values or the
            identical-manifest refusal fires.
        config: Capital and cost models, identical across cells.
        risk_factory: A fresh evaluator per cell.
        objective: The ranking rule, recorded by name.

    Returns:
        The surface: every cell with its numbers and manifest, the
        grid it came from, and statistics that follow from it.

    Raises:
        BacktestError: No axes, an empty or duplicate axis or value,
            or two cells producing the identical manifest.
    """
    named_axes = _check_axes(axes)
    names = tuple(name for name, _ in named_axes)
    cells: list[SensitivityCell] = []
    for assignment in itertools.product(*(values for _, values in named_axes)):
        parameters = tuple(zip(names, assignment, strict=True))
        strategy = build(dict(parameters))
        risk = risk_factory()
        result = run_backtest(data, strategy, config, risk=risk)
        cells.append(
            SensitivityCell(
                parameters=parameters,
                score=objective(result),
                numbers=OutOfSampleNumbers.from_result(result),
                manifest=build_manifest(result, config=config, risk=risk),
            )
        )
    return SensitivitySurface(
        dataset_id=data.dataset_id,
        dataset_version=data.version,
        slice_start=data.start,
        slice_end=data.end,
        objective=objective.name,
        axes=named_axes,
        cells=tuple(cells),
    )


def replay_sensitivity(
    root: Path,
    surface: SensitivitySurface,
    *,
    build: Callable[[Mapping[str, str]], Strategy],
    risk_factory: Callable[[], RiskEvaluator],
    objective: SelectionObjective = ENDING_EQUITY,
) -> tuple[BacktestResult, ...]:
    """Re-execute every cell of a surface and re-derive its numbers.

    The stored numbers are claims; replay turns them back into
    results. Verifying, failing closed at the first mismatch:

    1. The caller's objective is the one the surface recorded.
    2. Every manifest reproduces byte-for-byte — pinned dataset,
       narrowed to the recorded slice, run, artefacts compared
       (:func:`~harsh_quant_os.backtesting.manifest.run_from_manifest`),
       with the builder's strategy matching field for field.
    3. Every score re-derives from the reproduced run.
    4. Every cell's numbers re-derive from the reproduced run.

    Args:
        root: The data root holding ``clean/``.
        surface: The surface (fresh or loaded from JSON).
        build: The same declared grid builder the sweep used.
        risk_factory: A fresh evaluator per cell.
        objective: The ranking objective, matching the surface's.

    Returns:
        The reproduced results, one per cell in declared order.

    Raises:
        BacktestError: Objective mismatch, a manifest that does not
            reproduce (including a strategy that is not the recorded
            one), a score that does not follow, or numbers that do
            not follow.
        RecipeError: A pinned dataset version is absent or its stored
            hash no longer matches.
        ReproductionMismatch: A run executed but produced different
            artefacts.
    """
    if surface.objective != objective.name:
        raise BacktestError(
            f"the surface scored under {surface.objective!r} but replay was "
            f"given objective {objective.name!r}: scores cannot be re-derived "
            "under a different rule than the one recorded"
        )
    results: list[BacktestResult] = []
    for index, cell in enumerate(surface.cells):
        result = run_from_manifest(
            root,
            cell.manifest,
            strategy=build(dict(cell.parameters)),
            risk=risk_factory(),
        )
        score = objective(result)
        if score != cell.score:
            raise BacktestError(
                f"cell {index} ({cell.parameters!r}) scored {cell.score} in the "
                f"surface but {score} on replay — the stored score does not "
                "follow from the stored manifest"
            )
        numbers = OutOfSampleNumbers.from_result(result)
        if numbers != cell.numbers:
            raise BacktestError(
                f"cell {index} ({cell.parameters!r}): numbers did not reproduce "
                f"(surface: {cell.numbers}, replay: {numbers}) — the stored "
                "evidence does not follow from the stored manifest"
            )
        results.append(result)
    return tuple(results)
