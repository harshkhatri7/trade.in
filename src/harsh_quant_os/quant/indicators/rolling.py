"""Rolling indicators: trend, volatility, volume.

Every function here obeys the same three rules (quant-engine.md §3):

- **Right-aligned, no look-ahead.** The value at index ``i`` uses only
  ``values[i - window + 1] .. values[i]``. Appending a bar to the input can
  never change an earlier output — ``tests/quant/test_indicators.py``
  asserts that mechanically for every function in this package.
- **Documented warm-up.** The first ``window - 1`` outputs are NaN because
  no full window exists yet. That prefix is part of the formula, not a
  missing value, and it is asserted in the golden tests.
- **Deterministic.** Pure array maths over ``float64``: no wall clock, no
  randomness, no thread-order dependence. Rolling means and standard
  deviations are computed per window from a sliding view, so a value does
  not depend on how much data follows it.

Formulas (all over ``float64``, population statistics unless stated):

- ``sma(x, w)[i] = mean(x[i-w+1..i])`` for ``i >= w-1``.
- ``ema(x, span)[0] = x[0]``; thereafter
  ``out[i] = out[i-1] + alpha * (x[i] - out[i-1])`` with
  ``alpha = 2 / (span + 1)``. The first value seeds the recursion, so early
  outputs carry the seed's influence; there is no hidden SMA warm-up.
- ``rolling_std(x, w)[i] = std(x[i-w+1..i], ddof=0)`` — population
  standard deviation (the same convention as Bollinger bands below).
- ``rolling_zscore(x, w)[i] = (x[i] - mean) / std`` over the window;
  a flat window (``std == 0``) is undefined and yields NaN rather than an
  invented number.
- ``bollinger_bands(x, w, k)``: ``mid = sma(x, w)``,
  ``upper = mid + k * rolling_std(x, w)``, ``lower = mid - k * rolling_std(x, w)``.
- ``rolling_vwap(high, low, close, volume, w)`` over the window ending at
  ``i``: ``sum(typical * volume) / sum(volume)`` with
  ``typical = (high + low + close) / 3``; a window whose volume sums to
  zero yields NaN (no volume is not a price of zero).

None of these decide anything — they describe data for research.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray

from harsh_quant_os.quant.series import InvalidSeries, as_float_series, check_window

__all__ = [
    "BollingerBands",
    "bollinger_bands",
    "ema",
    "rolling_std",
    "rolling_vwap",
    "rolling_zscore",
    "sma",
]


def sma(
    values: NDArray[np.float64] | Sequence[float],
    window: int,
) -> NDArray[np.float64]:
    """Simple moving average, right-aligned.

    Args:
        values: The series to average. Must be finite and 1-D.
        window: Number of values per mean; ``1`` returns the input.

    Returns:
        ``len(values)`` float64 values; positions ``0 .. window-2`` are NaN
        (the warm-up prefix).

    Raises:
        InvalidSeries: The series is empty/non-1-D/non-finite, or the
            window is not a positive int or exceeds the series length.
    """
    x = as_float_series(values, name="values")
    check_window(window, x.size)
    out = np.full(x.size, np.nan, dtype=np.float64)
    if window == 1:
        out[:] = x
        return out
    means = sliding_window_view(x, window).mean(axis=-1)
    out[window - 1 :] = means
    return out


def ema(
    values: NDArray[np.float64] | Sequence[float],
    span: int,
) -> NDArray[np.float64]:
    """Exponential moving average seeded by the first value.

    Args:
        values: The series to smooth. Must be finite and 1-D.
        span: The EMA span (``alpha = 2 / (span + 1)``); ``span = 1``
            yields ``alpha = 1`` and returns the input unchanged.

    Returns:
        ``len(values)`` float64 values with no NaN prefix: position 0 is
        the seed ``values[0]``. Early outputs are influenced by the seed —
        documented here rather than masked by a warm-up cut.

    Raises:
        InvalidSeries: The series is empty/non-1-D/non-finite, or the
            span is not a positive int or exceeds the series length.
    """
    x = as_float_series(values, name="values")
    check_window(span, x.size, name="span")
    alpha = 2.0 / (span + 1)
    out = np.empty(x.size, dtype=np.float64)
    out[0] = x[0]
    # Sequential on purpose: each step depends on the previous one, so the
    # result is bit-identical across runs on any platform.
    for i in range(1, x.size):
        out[i] = out[i - 1] + alpha * (x[i] - out[i - 1])
    return out


def rolling_std(
    values: NDArray[np.float64] | Sequence[float],
    window: int,
) -> NDArray[np.float64]:
    """Rolling population standard deviation (``ddof=0``), right-aligned.

    Args:
        values: The series. Must be finite and 1-D.
        window: Number of values per standard deviation.

    Returns:
        ``len(values)`` float64 values; positions ``0 .. window-2`` are NaN.

    Raises:
        InvalidSeries: The series is empty/non-1-D/non-finite, or the
            window is not a positive int or exceeds the series length.
    """
    x = as_float_series(values, name="values")
    check_window(window, x.size)
    out = np.full(x.size, np.nan, dtype=np.float64)
    out[window - 1 :] = sliding_window_view(x, window).std(axis=-1, ddof=0)
    return out


def rolling_zscore(
    values: NDArray[np.float64] | Sequence[float],
    window: int,
) -> NDArray[np.float64]:
    """Rolling z-score of the last value against its window, right-aligned.

    Args:
        values: The series. Must be finite and 1-D.
        window: Number of values per mean/standard deviation.

    Returns:
        ``len(values)`` float64 values; positions ``0 .. window-2`` are NaN
        (warm-up), and a flat window yields NaN (z is undefined when the
        window has no variation — surfaced, never faked as 0).

    Raises:
        InvalidSeries: The series is empty/non-1-D/non-finite, or the
            window is not a positive int or exceeds the series length.
    """
    x = as_float_series(values, name="values")
    check_window(window, x.size)
    out = np.full(x.size, np.nan, dtype=np.float64)
    windows = sliding_window_view(x, window)
    means = windows.mean(axis=-1)
    stds = windows.std(axis=-1, ddof=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        scores = np.where(
            stds > 0.0, (windows[:, -1] - means) / np.where(stds > 0.0, stds, 1.0), np.nan
        )
    out[window - 1 :] = scores
    return out


@dataclass(frozen=True, slots=True)
class BollingerBands:
    """Mid, upper and lower bands — three parallel series of one formula."""

    mid: NDArray[np.float64]
    upper: NDArray[np.float64]
    lower: NDArray[np.float64]


def bollinger_bands(
    values: NDArray[np.float64] | Sequence[float],
    window: int,
    k: float = 2.0,
) -> BollingerBands:
    """Bollinger bands: SMA +/- k population standard deviations.

    Args:
        values: The series. Must be finite and 1-D.
        window: Number of values per band (must not exceed the series).
        k: Multiplier of the standard deviation; must be finite and > 0.

    Returns:
        Three aligned ``len(values)`` series sharing the warm-up prefix
        ``0 .. window-2``.

    Raises:
        InvalidSeries: Any series or window problem as for ``sma``, or
            ``k`` is not finite and positive.
    """
    if not np.isfinite(k) or k <= 0.0:
        raise InvalidSeries(f"k must be finite and > 0, got {k!r}")
    mid = sma(values, window)
    sd = rolling_std(values, window)
    return BollingerBands(mid=mid, upper=mid + k * sd, lower=mid - k * sd)


def rolling_vwap(
    high: NDArray[np.float64] | Sequence[float],
    low: NDArray[np.float64] | Sequence[float],
    close: NDArray[np.float64] | Sequence[float],
    volume: NDArray[np.float64] | Sequence[float],
    window: int,
) -> NDArray[np.float64]:
    """Rolling volume-weighted average price over typical price.

    Args:
        high: High prices, finite and 1-D.
        low: Low prices, finite and 1-D.
        close: Close prices, finite and 1-D.
        volume: Volumes, finite, 1-D and non-negative (a negative volume
            raises — it cannot be corrected silently).
        window: Number of bars per VWAP.

    Returns:
        ``len(close)`` float64 values; positions ``0 .. window-2`` are NaN,
        and a window with zero total volume yields NaN.

    Raises:
        InvalidSeries: Lengths disagree, any series is empty/non-1-D/
        non-finite, a volume is negative, or the window is invalid.
    """
    h = as_float_series(high, name="high")
    lo = as_float_series(low, name="low")
    c = as_float_series(close, name="close")
    v = as_float_series(volume, name="volume")
    if not (h.size == lo.size == c.size == v.size):
        raise InvalidSeries(
            "high, low, close and volume must have equal length, got "
            f"{h.size}, {lo.size}, {c.size}, {v.size}"
        )
    check_window(window, c.size)
    if np.any(v < 0.0):
        bad = int(np.argmax(v < 0.0))
        raise InvalidSeries(f"volume is negative at index {bad}; refusing to weight by it")

    typical = (h + lo + c) / 3.0
    weighted = sliding_window_view(typical * v, window).sum(axis=-1)
    totals = sliding_window_view(v, window).sum(axis=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        vwap = np.where(totals > 0.0, weighted / np.where(totals > 0.0, totals, 1.0), np.nan)
    out = np.full(c.size, np.nan, dtype=np.float64)
    out[window - 1 :] = vwap
    return out
