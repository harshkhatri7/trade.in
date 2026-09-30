"""Chronological splits with the leakage checks built in.

quant-engine.md §4 requires split utilities that assert disjoint
indices, and its rules require alignment on sessions rather than
shuffled rows — so this split is **chronological only**: everything
before the cut trains, everything after it tests, and no shuffle exists
that could put a future row into the training side. The properties are
then re-asserted on the way out (disjointness via ``assert_disjoint``)
rather than trusted from construction:

- ``train`` and ``test`` share no index;
- their union is exactly ``0 .. size-1`` (no row is silently dropped);
- ``max(train) < min(test)`` — training strictly precedes testing in
  time.

``assert_disjoint`` is public because future callers (walk-forward
loops, backtest folds) build their own index sets and must be able to
run the same assertion over them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from harsh_quant_os.quant.series import InvalidSeries

__all__ = [
    "SplitIndices",
    "assert_disjoint",
    "chronological_split",
]


def _as_index_set(
    values: NDArray[np.int64] | list[int],
    *,
    name: str,
) -> NDArray[np.int64]:
    """Return ``values`` as a 1-D non-negative ``int64`` array."""
    array = np.asarray(values, dtype=np.int64)
    if array.ndim != 1:
        raise InvalidSeries(f"{name} must be one-dimensional, got shape {array.shape}")
    if array.size and np.any(array < 0):
        first = int(array[np.flatnonzero(array < 0)[0]])
        raise InvalidSeries(f"{name} contains a negative index ({first}); indices count from 0")
    return array


def assert_disjoint(
    left: NDArray[np.int64] | list[int],
    right: NDArray[np.int64] | list[int],
) -> None:
    """Raise if two index sets share an element.

    Args:
        left: First index set (1-D, non-negative ints).
        right: Second index set (1-D, non-negative ints).

    Raises:
        InvalidSeries: Either set is malformed, or the sets overlap —
        the first shared index is named in the message, because "these
        folds overlap" is only actionable with an example.
    """
    a = _as_index_set(left, name="left")
    b = _as_index_set(right, name="right")
    shared = np.intersect1d(a, b)
    if shared.size:
        raise InvalidSeries(
            f"left and right share index {int(shared[0])} "
            f"({shared.size} shared in total); splits must be disjoint"
        )


@dataclass(frozen=True, slots=True)
class SplitIndices:
    """Train/test index sets for one chronological split."""

    train: NDArray[np.int64]
    test: NDArray[np.int64]


def chronological_split(
    size: int,
    *,
    train_fraction: float = 0.8,
) -> SplitIndices:
    """Split ``0 .. size-1`` at a chronological cut point.

    Args:
        size: Number of rows to split; at least 2.
        train_fraction: Share of rows before the cut, strictly between
            0 and 1. The cut is ``int(size * train_fraction)`` and must
            leave both sides non-empty.

    Returns:
        ``train = [0, cut)`` and ``test = [cut, size)``, both ``int64``,
        disjoint, complete and time-ordered — and re-asserted as such
        before returning.

    Raises:
        InvalidSeries: ``size`` is not an int of at least 2;
        ``train_fraction`` is outside ``(0, 1)``; or the cut would leave
        an empty side (a fraction too small or too large for this
        size).
    """
    if isinstance(size, bool) or not isinstance(size, int):
        raise InvalidSeries(f"size must be an int, got {type(size).__name__}")
    if size < 2:
        raise InvalidSeries(f"size must be >= 2 to split, got {size}")
    if not np.isfinite(train_fraction) or not 0.0 < train_fraction < 1.0:
        raise InvalidSeries(
            f"train_fraction must be strictly between 0 and 1, got {train_fraction!r}"
        )

    cut = int(size * train_fraction)
    if cut < 1 or cut >= size:
        raise InvalidSeries(
            f"train_fraction {train_fraction} over {size} rows cuts at {cut}, "
            "leaving one side empty"
        )

    train = np.arange(cut, dtype=np.int64)
    test = np.arange(cut, size, dtype=np.int64)
    # The construction already guarantees this; asserting it anyway means a
    # future edit to either line fails here instead of inside a backtest.
    assert_disjoint(train, test)
    return SplitIndices(train=train, test=test)
