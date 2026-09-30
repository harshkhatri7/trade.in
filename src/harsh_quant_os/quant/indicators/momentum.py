"""Momentum indicators: RSI and MACD.

Both are sequential recursions (like ``ema``), so each output depends only
on inputs at or before its index and the result is bit-identical across
runs. Formulas are stated here and each one is hand-checked in
``tests/quant/test_indicators.py``.

**RSI (Wilder, 1978).** With ``d[i] = x[i] - x[i-1]``,
``gain[i] = max(d[i], 0)``, ``loss[i] = max(-d[i], 0)``:

- the first averages are the arithmetic means of the first ``window`` gains
  and losses (index ``window`` onward);
- thereafter ``avg = (avg * (window - 1) + next) / window`` (Wilder's
  smoothing, which is an EMA with ``alpha = 1 / window``);
- ``rsi[i] = 100 * avg_gain / (avg_gain + avg_loss)``.

Edge policies, decided here so no caller invents one:

- a flat series (no gain and no loss in the window) is neutral → ``50``;
- no loss → ``100``; no gain → ``0``.

Positions ``0 .. window`` are NaN: the first full set of ``window`` diffs
ends at index ``window``.

**MACD.** ``macd = ema(close, fast) - ema(close, slow)`` with
``fast < slow``; ``signal = ema(macd, signal)``; ``histogram = macd -
signal``. Both EMAs use this package's first-value seed (see ``ema``), so
the lines start at index 0 with no NaN prefix; the early values are
seed-influenced, which is stated rather than hidden behind a cut.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from harsh_quant_os.quant.indicators.rolling import ema
from harsh_quant_os.quant.series import InvalidSeries, as_float_series, check_window

__all__ = [
    "Macd",
    "macd",
    "rsi",
]


def rsi(
    values: NDArray[np.float64] | Sequence[float],
    window: int = 14,
) -> NDArray[np.float64]:
    """Wilder's relative strength index.

    Args:
        values: The price series. Must be finite and 1-D and long enough
            for ``window`` differences (``len > window``).
        window: Wilder smoothing length (conventionally 14).

    Returns:
        ``len(values)`` float64 values in ``[0, 100]``; positions
        ``0 .. window`` are NaN (warm-up); flat stretches are 50 as
        documented in the module docstring.

    Raises:
        InvalidSeries: The series is empty/non-1-D/non-finite, the window
        is invalid, or ``len(values) <= window`` (there would be no
        complete first average).
    """
    x = as_float_series(values, name="values")
    check_window(window, x.size)
    if x.size <= window:
        raise InvalidSeries(
            f"rsi needs more than {window} values to seed its first average, got {x.size}"
        )

    diff = np.diff(x)
    gains = np.maximum(diff, 0.0)
    losses = np.maximum(-diff, 0.0)

    out = np.full(x.size, np.nan, dtype=np.float64)
    avg_gain = float(gains[:window].mean())
    avg_loss = float(losses[:window].mean())
    out[window] = _rsi_value(avg_gain, avg_loss)

    for i in range(window + 1, x.size):
        avg_gain = (avg_gain * (window - 1) + float(gains[i - 1])) / window
        avg_loss = (avg_loss * (window - 1) + float(losses[i - 1])) / window
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    """RSI from two averages, with the flat/up/down policies applied."""
    if avg_gain == 0.0 and avg_loss == 0.0:
        return 50.0
    if avg_loss == 0.0:
        return 100.0
    if avg_gain == 0.0:
        return 0.0
    return 100.0 * avg_gain / (avg_gain + avg_loss)


@dataclass(frozen=True, slots=True)
class Macd:
    """MACD line, its signal line, and their difference."""

    macd: NDArray[np.float64]
    signal: NDArray[np.float64]
    histogram: NDArray[np.float64]


def macd(
    values: NDArray[np.float64] | Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Macd:
    """Moving-average convergence/divergence.

    Args:
        values: The price series. Must be finite and 1-D.
        fast: Fast EMA span; must be a positive int.
        slow: Slow EMA span; must be a positive int strictly greater than
            ``fast`` (fast minus slow would be a sign flip, not MACD).
        signal: Signal EMA span; must be a positive int.

    Returns:
        Three aligned ``len(values)`` series (no NaN prefix — see module
        docstring).

    Raises:
        InvalidSeries: Any series/span problem, ``fast >= slow``, or a
            span longer than the series.
    """
    x = as_float_series(values, name="values")
    check_window(fast, x.size, name="fast")
    check_window(slow, x.size, name="slow")
    check_window(signal, x.size, name="signal")
    if fast >= slow:
        raise InvalidSeries(f"fast ({fast}) must be < slow ({slow}), or the sign flips")

    line = ema(x, fast) - ema(x, slow)
    signal_line = ema(line, signal)
    return Macd(macd=line, signal=signal_line, histogram=line - signal_line)
