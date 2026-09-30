"""Input rules shared by every quant calculation.

The quant engine's contract (``docs/architecture/quant-engine.md`` §3) says
missing values are surfaced, never dropped or computed through, and that the
same inputs must produce the same outputs across runs. That starts at the
boundary: a series that cannot be computed *as given* raises here, before a
single window is rolled.

What raises:

- an empty series or a non-1-D array;
- a value that is NaN or infinite — callers must resolve missing data
  explicitly and record the decision in their recipe, not let it flow into
  a mean;
- a window that is not a positive integer, or that is longer than the
  series — an all-NaN answer would be a silent wrong result;
- negative volume (``quant.indicators.rolling_vwap``).

Outputs may still contain NaN: every right-aligned window has a documented
warm-up prefix. Warm-up NaN is a statement about the window, not a missing
value, and each function documents exactly where it ends.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "InvalidSeries",
    "as_float_series",
    "check_window",
]


class InvalidSeries(ValueError):
    """An input series cannot be computed as given."""


def as_float_series(
    values: NDArray[np.float64] | Sequence[float],
    *,
    name: str,
) -> NDArray[np.float64]:
    """Return ``values`` as a finite, one-dimensional ``float64`` array.

    Args:
        values: The series to validate. Lists and tuples are converted;
            arrays are returned as-is when already ``float64``.
        name: The argument name used in error messages, so a failure names
            the series the caller got wrong (``close``, ``volume``, ...).

    Returns:
        A ``float64`` 1-D array. The original array is never modified.

    Raises:
        InvalidSeries: The input is empty, not 1-D, or contains NaN or
            infinity.
    """
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise InvalidSeries(f"{name} must be one-dimensional, got shape {array.shape}")
    if array.size == 0:
        raise InvalidSeries(f"{name} is empty; a window cannot be computed over no data")
    if not np.all(np.isfinite(array)):
        bad = int(np.argmax(~np.isfinite(array)))
        raise InvalidSeries(
            f"{name} contains a non-finite value at index {bad}; resolve missing "
            "data explicitly in the recipe instead of computing through it"
        )
    return array


def check_window(window: int, size: int, *, name: str = "window") -> None:
    """Validate a window length against the series it will roll over.

    Args:
        window: The requested window length.
        size: The length of the series the window rolls over.
        name: Argument name used in error messages.

    Raises:
        InvalidSeries: ``window`` is not a positive ``int`` (booleans are
            rejected even though ``bool`` subclasses ``int``), or is longer
            than ``size``.
    """
    if isinstance(window, bool) or not isinstance(window, int):
        raise InvalidSeries(f"{name} must be an int, got {type(window).__name__}")
    if window < 1:
        raise InvalidSeries(f"{name} must be >= 1, got {window}")
    if window > size:
        raise InvalidSeries(
            f"{name} of {window} is longer than the {size}-value series it rolls over; "
            "every value would be warm-up NaN"
        )
