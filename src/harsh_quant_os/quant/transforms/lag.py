"""Shifting: ``lag`` with an enforced direction.

quant-engine.md §4 names "shifting the wrong direction" as a leakage
risk and demands explicit lag/shift semantics with direction
assertions. The semantics here are deliberately one-sided:

- ``lag(values, periods)[i] = values[i - periods]`` — the output only
  ever reaches **backwards**, so a positive ``periods`` can never place
  a future value anywhere;
- a **negative** ``periods`` would read the future, so it is refused by
  name rather than given a convenience alias;
- ``periods = 0`` is refused too: it is a no-op, and a no-op silently
  standing in for a real shift is how an intended lag disappears from a
  recipe;
- the first ``periods`` outputs are NaN (those positions have no
  earlier data), and ``periods`` must stay below the series length or
  everything would be NaN.

Appending data cannot change any earlier output — asserted mechanically
in ``tests/quant/test_transforms.py``.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from harsh_quant_os.quant.series import InvalidSeries, as_float_series, check_window

__all__ = ["lag"]


def lag(
    values: NDArray[np.float64] | Sequence[float],
    periods: int,
) -> NDArray[np.float64]:
    """Shift a series into the past by ``periods`` positions.

    Args:
        values: The series, 1-D, finite, non-empty.
        periods: How far back to reach; a positive int strictly less
            than ``len(values)``.

    Returns:
        ``len(values)`` float64 values; the first ``periods`` positions
        are NaN and ``out[i] = values[i - periods]`` thereafter.

    Raises:
        InvalidSeries: ``periods`` is not an int, is negative (would
        read the future), is zero, or reaches the series length; or the
        series itself is invalid.
    """
    x = as_float_series(values, name="values")
    if isinstance(periods, bool) or not isinstance(periods, int):
        raise InvalidSeries(f"periods must be an int, got {type(periods).__name__}")
    if periods < 0:
        raise InvalidSeries(
            f"periods must not be negative (got {periods}): a negative shift would "
            "read future values, and the engine only shifts into the past"
        )
    check_window(periods, x.size, name="periods")
    if periods >= x.size:
        raise InvalidSeries(
            f"periods of {periods} must be less than the {x.size}-value series; "
            "every output would be warm-up NaN"
        )

    out = np.full(x.size, np.nan, dtype=np.float64)
    out[periods:] = x[: x.size - periods]
    return out
