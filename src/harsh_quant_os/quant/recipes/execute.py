"""Executing a recipe: pinned bars in, a reproducible matrix out.

:meth:`execute` is the only way a recipe becomes numbers, and it does
exactly three things, in this order:

1. :meth:`recipe.validate() <FeatureRecipe.validate>` — so a hand-built
   or mutated recipe cannot bypass the rules (unique names, resolvable
   sources, known ops);
2. **the version pin is compared against the batch** — the recipe names
   a dataset and a content-addressed version; if the bars are a
   different dataset or a different version, execution refuses rather
   than producing a matrix that looks like the pinned one but is not
   (quant-engine.md §3 rule 7);
3. each feature runs through the whitelist in declaration order, with a
   source that is either an input column or an *earlier* output — the
   order makes forward (future) references unrepresentable, so the DAG
   cannot encode look-ahead.

The returned :class:`FeatureMatrix` carries the recipe's hash, the
dataset identity it was computed from, and the row times, so anything
downstream can restate its own provenance without re-deriving it.
Warm-up NaN survives into the matrix: rows are never dropped or filled
here — that decision belongs to the recipe's recorded ``nan_policy``,
and dropping rows would desynchronise features from their bars.

Determinism (§3 rule 1): every step is fixed-order deterministic
arithmetic on the arrays given, so two executions of the same recipe on
the same batch are bit-identical — asserted mechanically in
``tests/quant/test_recipes.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from harsh_quant_os.quant.recipes.bars import BarBatch
from harsh_quant_os.quant.recipes.ops import OPS
from harsh_quant_os.quant.recipes.recipe import FeatureRecipe, RecipeError
from harsh_quant_os.quant.series import InvalidSeries

__all__ = ["FeatureMatrix", "execute"]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class FeatureMatrix:
    """One executed recipe's output, with its provenance attached.

    ``values`` is ``len(row_times) x len(columns)`` float64; NaN only
    ever appears as documented warm-up or as whatever the recorded
    nan policy leaves behind — this object never drops a row.
    """

    values: NDArray[np.float64]
    columns: tuple[str, ...]
    row_times: NDArray[np.int64]
    recipe_hash: str
    dataset_id: str
    dataset_version: str

    def __post_init__(self) -> None:
        values = np.array(self.values, dtype=np.float64, copy=True)
        if values.ndim != 2:
            raise InvalidSeries(f"feature matrix must be 2-D, got shape {values.shape}")
        times = np.array(self.row_times, dtype=np.int64, copy=True)
        if times.ndim != 1:
            raise InvalidSeries(f"row_times must be 1-D, got shape {times.shape}")
        if values.shape[0] != times.size:
            raise InvalidSeries(f"matrix has {values.shape[0]} rows but row_times has {times.size}")
        if values.shape[1] != len(self.columns):
            raise InvalidSeries(
                f"matrix has {values.shape[1]} columns but {len(self.columns)} names were given"
            )
        for name in self.columns:
            if not name or name != name.strip():
                raise InvalidSeries(f"column name {name!r} must be non-empty and trimmed")
        if not _SHA256_RE.fullmatch(self.recipe_hash):
            raise InvalidSeries(
                f"recipe_hash must be a 64-character lowercase SHA-256, got {self.recipe_hash!r}"
            )
        if not self.dataset_id or not self.dataset_id.strip():
            raise InvalidSeries("dataset_id must not be empty")
        if not _SHA256_RE.fullmatch(self.dataset_version):
            raise InvalidSeries(
                "dataset_version must be a 64-character lowercase SHA-256, "
                f"got {self.dataset_version!r}"
            )
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "row_times", times)

    @property
    def shape(self) -> tuple[int, int]:
        """``(rows, features)`` of the matrix."""
        return self.values.shape

    def nan_counts(self) -> tuple[int, ...]:
        """NaN count per column — the missing values, surfaced per feature."""
        return tuple(int(count) for count in np.isnan(self.values).sum(axis=0))


def execute(recipe: FeatureRecipe, bars: BarBatch) -> FeatureMatrix:
    """Run ``recipe`` over ``bars`` and return the feature matrix.

    Args:
        recipe: The recipe; validated first, every time.
        bars: The pinned input batch — its name and version must equal
            the recipe's :class:`~harsh_quant_os.quant.recipes.recipe.DatasetRef`.

    Returns:
        A :class:`FeatureMatrix` with one column per declared feature,
        in declaration order, plus the recipe hash, dataset identity and
        row times.

    Raises:
        RecipeError: The recipe fails validation, or the bars are a
        different dataset or a different version than the recipe pins.
        The message names both sides so the mismatch is diagnosable.
        InvalidSeries: An op produced a different number of rows than
        it was given (only reachable by a new op breaking its
        contract — the whitelisted ones all preserve length).
    """
    recipe.validate()
    reference = recipe.inputs[0]
    if bars.name != reference.dataset_id:
        raise RecipeError(
            f"recipe is pinned to dataset {reference.dataset_id!r} but the bars are "
            f"{bars.name!r}; refusing to compute on different data"
        )
    if bars.version != reference.version:
        raise RecipeError(
            f"recipe is pinned to {reference.dataset_id} version {reference.version} but the "
            f"bars are version {bars.version}; re-pin the recipe deliberately if the dataset "
            "changed — it is never re-run silently on other data"
        )

    available: dict[str, NDArray[np.float64]] = {
        "open": bars.open,
        "high": bars.high,
        "low": bars.low,
        "close": bars.close,
        "volume": bars.volume,
    }
    outputs: list[NDArray[np.float64]] = []
    for feature in recipe.features:
        source = available[feature.source]  # validated: column or earlier output
        # A chained source may carry warm-up NaN (windowed features all
        # do). Primitives refuse to compute through non-finite input —
        # an undefined region is not data — so refuse here too, naming
        # the feature and the row rather than letting the primitive
        # report an index into an unnamed array. Bar columns are finite
        # by BarBatch's contract; only an earlier feature can fail this.
        if not bool(np.all(np.isfinite(source))):
            row = int(np.flatnonzero(~np.isfinite(source))[0])
            raise InvalidSeries(
                f"feature {feature.name!r} reads {feature.source!r}, which has no finite "
                f"value at row {row} (warm-up or missing data); primitives never compute "
                "through NaN, so a chained source must be finite (quant-engine.md section "
                "3 rule 3)"
            )
        produced = OPS[feature.op].apply(source, dict(feature.params))
        if produced.shape != bars.time.shape:
            raise InvalidSeries(
                f"op {feature.op!r} produced shape {produced.shape} from {bars.time.shape}; "
                "every feature op must preserve the row count"
            )
        outputs.append(produced)
        available[feature.name] = produced

    return FeatureMatrix(
        values=np.column_stack(outputs),
        columns=tuple(feature.name for feature in recipe.features),
        row_times=bars.time,
        recipe_hash=recipe.recipe_hash(),
        dataset_id=reference.dataset_id,
        dataset_version=reference.version,
    )
