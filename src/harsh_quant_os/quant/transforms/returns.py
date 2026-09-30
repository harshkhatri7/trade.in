"""Horizon transforms: simple returns, log returns, forward labels.

All three align with the input: ``len(out) == len(close)``, positions
that cannot be computed yet are the documented NaN prefix/suffix rather
than dropped rows (quant-engine.md §3 rule 3).

- ``simple_returns(close)[i] = close[i] / close[i-1] - 1`` for
  ``i >= 1``; position 0 is NaN (there is no previous price). A zero
  denominator raises — a return from zero is undefined, not infinite.
- ``log_returns(close)[i] = ln(close[i] / close[i-1])`` for ``i >= 1``;
  position 0 is NaN. Prices must be strictly positive, so a
  non-positive price raises with its index.
- ``forward_return(close, horizon)`` is a **label**, not an indicator:
  ``out[i] = close[i+horizon] / close[i] - 1`` for every ``i`` whose
  horizon still fits inside the sample, and the last ``horizon``
  positions are NaN because that outcome has not happened yet — the NaN
  tail is the label's availability boundary. It reads strictly forward
  from each point by design (that is what a label is); appending data
  never changes a label that was already computable, which
  ``tests/quant/test_transforms.py`` asserts mechanically.

Nothing here timestamps anything: these are array transforms. The
``label_time >= info_time`` assertion over real timelines arrives with
the recipe layer that carries timestamps.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from harsh_quant_os.quant.series import InvalidSeries, as_float_series, check_window

__all__ = [
    "forward_return",
    "log_returns",
    "simple_returns",
]


def simple_returns(
    close: NDArray[np.float64] | Sequence[float],
) -> NDArray[np.float64]:
    """Period-to-period simple returns of a price series.

    Args:
        close: Prices, 1-D, finite, at least two values; no zero value
            (a return from zero has no defined ratio).

    Returns:
        ``len(close)`` float64 values; position 0 is NaN, positions
        ``1 .. n-1`` are ``close[i] / close[i-1] - 1``.

    Raises:
        InvalidSeries: Fewer than two values, a non-finite or zero
        price (named by index), or a non-1-D input.
    """
    x = as_float_series(close, name="close")
    if x.size < 2:
        raise InvalidSeries(f"returns need at least 2 values to compare, got {x.size}")
    zero = np.flatnonzero(x[:-1] == 0.0)
    if zero.size:
        raise InvalidSeries(
            f"close is zero at index {int(zero[0])}; a return from zero is undefined"
        )
    out = np.full(x.size, np.nan, dtype=np.float64)
    out[1:] = x[1:] / x[:-1] - 1.0
    return out


def log_returns(
    close: NDArray[np.float64] | Sequence[float],
) -> NDArray[np.float64]:
    """Period-to-period log returns of a price series.

    Args:
        close: Prices, 1-D, finite, at least two values, all strictly
            positive (``ln`` of a non-positive price does not exist).

    Returns:
        ``len(close)`` float64 values; position 0 is NaN, positions
        ``1 .. n-1`` are ``ln(close[i] / close[i-1])``.

    Raises:
        InvalidSeries: Fewer than two values, a non-positive or
        non-finite price (named by index), or a non-1-D input.
    """
    x = as_float_series(close, name="close")
    if x.size < 2:
        raise InvalidSeries(f"returns need at least 2 values to compare, got {x.size}")
    non_positive = np.flatnonzero(x <= 0.0)
    if non_positive.size:
        i = int(non_positive[0])
        raise InvalidSeries(
            f"close has a non-positive value ({x[i]!r}) at index {i}; "
            "log returns need strictly positive prices"
        )
    out = np.full(x.size, np.nan, dtype=np.float64)
    out[1:] = np.log(x[1:] / x[:-1])
    return out


def forward_return(
    close: NDArray[np.float64] | Sequence[float],
    horizon: int,
) -> NDArray[np.float64]:
    """Forward simple return over ``horizon`` bars — a label.

    Args:
        close: Prices, 1-D, finite, strictly longer than ``horizon``;
            no zero value inside the labelable region.
        horizon: Bars to look forward; a positive int strictly less
            than ``len(close)``.

    Returns:
        ``len(close)`` float64 values: ``close[i+horizon] /
        close[i] - 1`` for ``i < len(close) - horizon``, then NaN for
        the last ``horizon`` positions — those outcomes are not yet
        observable, and an unobservable label is NaN, never guessed.

    Raises:
        InvalidSeries: Invalid horizon (not a positive int, reaching
        the series length), a too-short or zero/non-finite series, or a
        non-1-D input.
    """
    x = as_float_series(close, name="close")
    check_window(horizon, x.size, name="horizon")
    if horizon >= x.size:
        raise InvalidSeries(
            f"horizon of {horizon} must be less than the {x.size}-value series; "
            "no label would ever be observable"
        )
    labelable = x.size - horizon
    zero = np.flatnonzero(x[:labelable] == 0.0)
    if zero.size:
        raise InvalidSeries(
            f"close is zero at index {int(zero[0])}; a forward return from zero is undefined"
        )
    out = np.full(x.size, np.nan, dtype=np.float64)
    out[:labelable] = x[horizon:] / x[:labelable] - 1.0
    return out
