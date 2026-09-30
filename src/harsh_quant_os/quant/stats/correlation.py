"""Dependence measures: sample autocorrelation and Pearson correlation.

Both are **whole-sample statistics**: they use exactly the values handed
in, in the order handed in, with no alignment or windowing (so the
right-alignment rule in quant-engine.md §3 does not apply to them — there
is no "point being computed"). Both are deterministic arithmetic.

**Autocorrelation** (biased / ``1/n`` estimator, so ``acf[0] = 1``
exactly)::

    acf(k) = Σ_{t=0}^{n-k-1} (x_t - x̄)(x_{t+k} - x̄)  /  Σ_{t=0}^{n-1} (x_t - x̄)²

``nlags`` is capped below the series length: a lag with no overlapping
pairs would be an invented number, not a correlation.

**Pearson product-moment correlation** between column ``a`` and column
``b``::

    r(a, b) = Σ (a_t - ā)(b_t - b̄)  /  sqrt( Σ (a_t - ā)² · Σ (b_t - b̄)² )

A constant column has zero variance, so its correlation with anything is
undefined (0/0) — that raises instead of returning a silent ``NaN`` or an
arbitrary ``0``. Neither function decides anything; both only describe
the sample they are given.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from harsh_quant_os.quant.series import InvalidSeries, as_float_series

__all__ = [
    "acf",
    "correlation_matrix",
]


def acf(
    values: NDArray[np.float64] | Sequence[float],
    nlags: int,
) -> NDArray[np.float64]:
    """Sample autocorrelation function through lag ``nlags``.

    Args:
        values: The series. Must be 1-D, non-empty, finite, and with
            non-zero variance.
        nlags: Highest lag to report; ``0`` returns just ``[1.0]``.
            Must be a non-negative int and strictly less than the series
            length (every reported lag needs at least one overlapping
            pair).

    Returns:
        ``nlags + 1`` float64 values: index ``k`` is the autocorrelation
        at lag ``k``, with ``out[0] == 1.0``.

    Raises:
        InvalidSeries: The series is empty/non-1-D/non-finite/constant,
            or ``nlags`` is not an int, is negative, or reaches the
            series length.
    """
    x = as_float_series(values, name="values")
    if isinstance(nlags, bool) or not isinstance(nlags, int):
        raise InvalidSeries(f"nlags must be an int, got {type(nlags).__name__}")
    if nlags < 0:
        raise InvalidSeries(f"nlags must be >= 0, got {nlags}")
    if nlags >= x.size:
        raise InvalidSeries(
            f"nlags of {nlags} needs at least {nlags + 1} values to overlap, got {x.size}"
        )

    centered = x - x.mean()
    denominator = float(centered @ centered)
    if denominator == 0.0:
        raise InvalidSeries("values are constant; autocorrelation has no variance to explain")

    out = np.empty(nlags + 1, dtype=np.float64)
    for k in range(nlags + 1):
        numerator = float(centered[: x.size - k] @ centered[k:])
        out[k] = numerator / denominator
    return out


def correlation_matrix(
    columns: Sequence[NDArray[np.float64] | Sequence[float]],
) -> NDArray[np.float64]:
    """Pearson correlation matrix over equally long columns.

    Args:
        columns: The columns to correlate, each the same length with at
            least two observations, every value finite, none constant.
            The matrix follows this order.

    Returns:
        An ``(m, m)`` float64 matrix: symmetric, with a 1.0 diagonal.
        For ``m = 1`` the result is ``[[1.0]]`` — a column always agrees
            with itself.

    Raises:
        InvalidSeries: ``columns`` is empty; lengths disagree (all
            lengths are named); any column has fewer than two
            observations, is empty/non-1-D/non-finite, or is constant.
    """
    if len(columns) == 0:
        raise InvalidSeries("columns is empty; a correlation matrix needs at least one column")

    arrays = [as_float_series(column, name=f"columns[{i}]") for i, column in enumerate(columns)]
    sizes = {array.size for array in arrays}
    if len(sizes) > 1:
        lengths = ", ".join(str(array.size) for array in arrays)
        raise InvalidSeries(f"columns must have equal length, got {lengths}")
    size = arrays[0].size
    if size < 2:
        raise InvalidSeries(f"correlation needs at least 2 observations per column, got {size}")

    matrix = np.vstack(arrays)
    variances = matrix.var(axis=1, ddof=0)
    for i, variance in enumerate(variances):
        if variance == 0.0:
            raise InvalidSeries(f"columns[{i}] is constant; its correlation is undefined")

    # np.corrcoef returns a 0-d array for a single column; the documented
    # contract is always a matrix, so the shape is restored here rather
    # than left to the caller.
    return np.atleast_2d(np.corrcoef(matrix))
