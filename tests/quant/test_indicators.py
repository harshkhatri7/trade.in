"""Golden-value, property and validation tests for the indicator library.

Three kinds of assertion, all required by quant-engine.md §3 and §7:

1. **Golden values.** Every indicator is compared against a value computed
   *by hand* in this file — fractions where the formula has them (RSI's
   Wilder recursion, EMA's seed arithmetic), exact decimals for variances.
   The expected numbers are never produced by calling the implementation
   twice.
2. **Properties.** No look-ahead (appending a future bar cannot change an
   earlier output), determinism (the same input yields bit-identical
   output), and no input mutation — asserted mechanically for every
   function, not by convention.
3. **Validation.** Non-finite input, bad windows and inconsistent series
   raise ``InvalidSeries`` instead of producing a number.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pytest

from harsh_quant_os.quant.indicators import (
    InvalidSeries,
    bollinger_bands,
    ema,
    macd,
    rolling_std,
    rolling_vwap,
    rolling_zscore,
    rsi,
    sma,
)

pytestmark = pytest.mark.quant

PRICES = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
#: A longer series built from an explicit arithmetic recipe — no RNG, so
#: the golden values below cannot drift with a generator change.
SERIES = np.array(
    [(i * 7 % 11) * 0.5 + i * 0.13 for i in range(40)],
    dtype=np.float64,
)

# --------------------------------------------------------------------------
# Golden values
# --------------------------------------------------------------------------


def test_sma_golden_values() -> None:
    np.testing.assert_array_equal(
        sma(PRICES, 2),
        np.array([np.nan, 1.5, 2.5, 3.5, 4.5]),
    )
    np.testing.assert_array_equal(sma(PRICES, 1), PRICES)
    np.testing.assert_array_equal(
        sma(PRICES, 5),
        np.array([np.nan, np.nan, np.nan, np.nan, 3.0]),
    )


def test_sma_matches_an_independent_window_loop() -> None:
    window = 7
    expected = np.full(SERIES.size, np.nan)
    for i in range(window - 1, SERIES.size):
        expected[i] = sum(float(v) for v in SERIES[i - window + 1 : i + 1]) / window
    np.testing.assert_allclose(sma(SERIES, window), expected, rtol=1e-12, atol=1e-12)


def test_ema_golden_values_for_span_two() -> None:
    # alpha = 2/3 seeded at 1: 1, 5/3, 23/9, 95/27, 365/81 — derived by hand.
    expected = np.array([1.0, 5 / 3, 23 / 9, 95 / 27, 365 / 81])
    np.testing.assert_allclose(ema(PRICES, 2), expected, rtol=1e-15)


def test_ema_alpha_one_returns_the_input() -> None:
    np.testing.assert_array_equal(ema(PRICES, 1), PRICES)


def test_ema_of_a_constant_series_is_that_constant() -> None:
    flat = np.full(12, 7.25)
    np.testing.assert_array_equal(ema(flat, 5), flat)


def test_rolling_std_golden_values_population_ddof_zero() -> None:
    # std({1, 2}) = 0.5, std({1, 2, 3}) = sqrt(2/3) — hand-checked.
    np.testing.assert_array_equal(
        rolling_std(np.array([1.0, 2.0, 3.0, 4.0]), 2),
        np.array([np.nan, 0.5, 0.5, 0.5]),
    )
    out = rolling_std(PRICES, 3)
    assert math.isnan(out[0]) and math.isnan(out[1])
    assert out[2] == pytest.approx(math.sqrt(2 / 3), rel=1e-15)


def test_rolling_zscore_golden_values_and_flat_window_policy() -> None:
    # Each window {n, n+1} has mean n+0.5 and std 0.5, so z = 1 for all.
    np.testing.assert_array_equal(
        rolling_zscore(np.array([1.0, 2.0, 3.0, 4.0]), 2),
        np.array([np.nan, 1.0, 1.0, 1.0]),
    )
    # A flat window has no variation: z is undefined, and undefined means
    # NaN — never an invented 0.
    np.testing.assert_array_equal(
        rolling_zscore(np.full(6, 7.0), 3),
        np.full(6, np.nan),
    )


def test_bollinger_golden_values() -> None:
    bands = bollinger_bands(PRICES, 3, k=2.0)
    sd = math.sqrt(2 / 3)
    np.testing.assert_array_equal(
        bands.mid,
        np.array([np.nan, np.nan, 2.0, 3.0, 4.0]),
    )
    np.testing.assert_allclose(
        bands.upper,
        np.array([np.nan, np.nan, 2 + 2 * sd, 3 + 2 * sd, 4 + 2 * sd]),
        rtol=1e-15,
    )
    np.testing.assert_allclose(
        bands.lower,
        np.array([np.nan, np.nan, 2 - 2 * sd, 3 - 2 * sd, 4 - 2 * sd]),
        rtol=1e-15,
    )


def test_rsi_golden_values_from_the_wilder_recursion() -> None:
    # Diffs alternate +1/-1. With window 3 the first averages are 2/3 gain
    # and 1/3 loss; the recursion is then worked through by hand with
    # exact fractions:
    #   i=3:  2/3 vs 1/3        -> 200/3
    #   i=4:  4/9 vs 5/9        -> 400/9
    #   i=5: 17/27 vs 10/27     -> 1700/27
    #   i=6: 34/81 vs 47/81     -> 3400/81
    #   i=7: 149/243 vs 94/243  -> 14900/243
    alternating = np.array([1, 2, 1, 2, 1, 2, 1, 2], dtype=np.float64)
    out = rsi(alternating, window=3)
    np.testing.assert_array_equal(out[:3], np.full(3, np.nan))
    expected = np.array(
        [
            200 / 3,
            400 / 9,
            1700 / 27,
            3400 / 81,
            14900 / 243,
        ]
    )
    # rtol=1e-13: the recursion rounds at each step; the values themselves
    # are exact fractions derived by hand above.
    np.testing.assert_allclose(out[3:], expected, rtol=1e-13)


def test_rsi_edge_policies_are_those_documented() -> None:
    flat = np.full(6, 5.0)
    np.testing.assert_array_equal(rsi(flat, window=3)[3:], np.full(3, 50.0))

    rising = np.arange(1.0, 8.0)
    np.testing.assert_array_equal(rsi(rising, window=3)[3:], np.full(4, 100.0))

    falling = np.arange(7.0, 0.0, -1.0)
    np.testing.assert_array_equal(rsi(falling, window=3)[3:], np.full(4, 0.0))


def test_macd_of_a_constant_series_is_zero_everywhere() -> None:
    flat = np.full(30, 41.5)
    result = macd(flat, fast=3, slow=6, signal=3)
    np.testing.assert_array_equal(result.macd, np.zeros(30))
    np.testing.assert_array_equal(result.signal, np.zeros(30))
    np.testing.assert_array_equal(result.histogram, np.zeros(30))


def test_macd_lines_reuse_the_documented_ema_seed() -> None:
    result = macd(SERIES, fast=4, slow=9, signal=3)
    np.testing.assert_allclose(
        result.macd,
        ema(SERIES, 4) - ema(SERIES, 9),
        rtol=0,
        atol=0,
    )
    np.testing.assert_allclose(
        result.histogram,
        result.macd - result.signal,
        rtol=0,
        atol=0,
    )


def test_rolling_vwap_golden_values() -> None:
    high = np.array([3.0, 4.0])
    low = np.array([1.0, 2.0])
    close = np.array([2.0, 3.0])
    volume = np.array([10.0, 30.0])

    # Window 1: vwap == typical price (2 and 3).
    np.testing.assert_array_equal(
        rolling_vwap(high, low, close, volume, window=1),
        np.array([2.0, 3.0]),
    )
    # Window 2: (2*10 + 3*30) / 40 = 110/40 = 2.75.
    np.testing.assert_array_equal(
        rolling_vwap(high, low, close, volume, window=2),
        np.array([np.nan, 2.75]),
    )


def test_rolling_vwap_zero_volume_window_is_nan() -> None:
    out = rolling_vwap(
        np.ones(4),
        np.ones(4),
        np.ones(4),
        np.zeros(4),
        window=2,
    )
    np.testing.assert_array_equal(out, np.full(4, np.nan))


# --------------------------------------------------------------------------
# Properties: no look-ahead, determinism, no mutation
# --------------------------------------------------------------------------


def _append_future(*arrays: np.ndarray) -> tuple[np.ndarray, ...]:
    """Extend every series by the same three synthetic future bars."""
    tail = 3
    return tuple(np.concatenate([a, a[-tail:] + 1.0]) for a in arrays)


def test_sma_has_no_lookahead() -> None:
    longer = np.concatenate([PRICES, [9.0, -4.0, 12.5]])
    np.testing.assert_array_equal(sma(PRICES, 2), sma(longer, 2)[: PRICES.size])


def test_rolling_std_has_no_lookahead() -> None:
    longer = np.concatenate([PRICES, [9.0, -4.0, 12.5]])
    np.testing.assert_array_equal(rolling_std(PRICES, 2), rolling_std(longer, 2)[: PRICES.size])


def test_rolling_zscore_has_no_lookahead() -> None:
    longer = np.concatenate([PRICES, [9.0, -4.0, 12.5]])
    np.testing.assert_array_equal(
        rolling_zscore(PRICES, 2),
        rolling_zscore(longer, 2)[: PRICES.size],
    )


def test_ema_has_no_lookahead() -> None:
    longer = np.concatenate([SERIES, [100.0, -50.0, 7.5]])
    np.testing.assert_array_equal(ema(SERIES, 5), ema(longer, 5)[: SERIES.size])


def test_rsi_has_no_lookahead() -> None:
    longer = np.concatenate([SERIES, [100.0, -50.0, 7.5]])
    np.testing.assert_array_equal(rsi(SERIES, 6), rsi(longer, 6)[: SERIES.size])


def test_macd_has_no_lookahead() -> None:
    longer = np.concatenate([SERIES, [100.0, -50.0, 7.5]])
    before = macd(SERIES, fast=4, slow=9, signal=3)
    after = macd(longer, fast=4, slow=9, signal=3)
    np.testing.assert_array_equal(before.macd, after.macd[: SERIES.size])
    np.testing.assert_array_equal(before.signal, after.signal[: SERIES.size])
    np.testing.assert_array_equal(before.histogram, after.histogram[: SERIES.size])


def test_bollinger_has_no_lookahead() -> None:
    longer = np.concatenate([PRICES, [9.0, -4.0, 12.5]])
    before = bollinger_bands(PRICES, 3, k=2.0)
    after = bollinger_bands(longer, 3, k=2.0)
    np.testing.assert_array_equal(before.mid, after.mid[: PRICES.size])
    np.testing.assert_array_equal(before.upper, after.upper[: PRICES.size])
    np.testing.assert_array_equal(before.lower, after.lower[: PRICES.size])


def test_rolling_vwap_has_no_lookahead() -> None:
    high = np.full(10, 3.0)
    low = np.full(10, 1.0)
    close = np.full(10, 2.0)
    volume = np.arange(1.0, 11.0)
    longer = _append_future(high, low, close, volume)
    high2, low2, close2, volume2 = longer
    np.testing.assert_array_equal(
        rolling_vwap(high, low, close, volume, 4),
        rolling_vwap(high2, low2, close2, volume2, 4)[:10],
    )


@pytest.mark.parametrize(
    "call",
    [
        lambda x: sma(x, 3),
        lambda x: rolling_std(x, 3),
        lambda x: rolling_zscore(x, 3),
        lambda x: ema(x, 3),
        lambda x: rsi(x, 3),
        lambda x: macd(x, fast=2, slow=4, signal=2).histogram,
        lambda x: bollinger_bands(x, 3).upper,
    ],
    ids=["sma", "rolling_std", "zscore", "ema", "rsi", "macd", "bollinger"],
)
def test_every_indicator_is_deterministic_and_leaves_input_alone(
    call: Callable[[np.ndarray], np.ndarray],
) -> None:
    first = call(SERIES.copy())
    second = call(SERIES.copy())
    np.testing.assert_array_equal(first, second)
    # The input array is never modified in place.
    untouched = SERIES.copy()
    call(SERIES)
    np.testing.assert_array_equal(SERIES, untouched)


def test_outputs_are_float64() -> None:
    assert sma(PRICES, 2).dtype == np.float64
    assert rolling_std(PRICES, 2).dtype == np.float64
    assert rsi(PRICES, 2).dtype == np.float64


def test_warmup_prefix_is_exactly_the_documented_length() -> None:
    window = 4
    out = rolling_std(SERIES, window)
    assert np.all(np.isnan(out[: window - 1]))
    assert np.all(np.isfinite(out[window - 1 :]))


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def test_nan_input_raises_instead_of_computing_through_it() -> None:
    bad = PRICES.copy()
    bad[2] = np.nan
    with pytest.raises(InvalidSeries, match="non-finite value at index 2"):
        sma(bad, 2)


def test_infinite_input_raises() -> None:
    bad = PRICES.copy()
    bad[0] = np.inf
    with pytest.raises(InvalidSeries, match="non-finite"):
        rsi(bad, 2)


def test_empty_input_raises() -> None:
    with pytest.raises(InvalidSeries, match="empty"):
        ema(np.array([], dtype=np.float64), 2)


def test_two_dimensional_input_raises() -> None:
    with pytest.raises(InvalidSeries, match="one-dimensional"):
        sma(np.ones((4, 2)), 2)


@pytest.mark.parametrize("window", [0, -3, 1.5, True, "3"])
def test_invalid_windows_raise(window: object) -> None:
    with pytest.raises(InvalidSeries, match="window"):
        sma(PRICES, window)  # type: ignore[arg-type]


def test_window_longer_than_the_series_raises() -> None:
    with pytest.raises(InvalidSeries, match="longer than"):
        sma(PRICES, 6)


def test_rsi_needs_more_values_than_its_window() -> None:
    with pytest.raises(InvalidSeries, match="more than 5 values"):
        rsi(PRICES, 5)


def test_macd_requires_fast_below_slow() -> None:
    with pytest.raises(InvalidSeries, match="must be < slow"):
        macd(SERIES, fast=9, slow=9, signal=3)


def test_bollinger_rejects_a_non_positive_multiplier() -> None:
    with pytest.raises(InvalidSeries, match="k must be"):
        bollinger_bands(PRICES, 3, k=0.0)


def test_vwap_rejects_mismatched_lengths() -> None:
    with pytest.raises(InvalidSeries, match="equal length"):
        rolling_vwap(np.ones(5), np.ones(5), np.ones(5), np.ones(4), window=2)


def test_vwap_rejects_negative_volume() -> None:
    volume = np.ones(5)
    volume[3] = -1.0
    with pytest.raises(InvalidSeries, match="negative at index 3"):
        rolling_vwap(np.ones(5), np.ones(5), np.ones(5), volume, window=2)
