"""Golden, property and validation tests for ``quant.transforms``.

The leakage assertions quant-engine.md §4 asks for are made mechanically
here:

- **shifting direction** — ``lag`` refuses a negative shift by name and
  agrees with ``out[i] = values[i - periods]`` on hand-picked values;
- **scaling fit sample** — the scaler's statistics come from exactly
  what was passed, transforming future data cannot re-centre it, and the
  fitted object is frozen;
- **disjoint splits** — train/test sets are disjoint, complete and
  time-ordered for every parameter combination, checked with NumPy
  rather than with the helper under test;
- **labels** — the unobservable tail of a forward label is NaN, and
  appending data never revises a label that was already computable.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from harsh_quant_os.quant.transforms import (
    InvalidSeries,
    SplitIndices,
    StandardScaler,
    assert_disjoint,
    chronological_split,
    forward_return,
    lag,
    log_returns,
    simple_returns,
)

pytestmark = pytest.mark.quant

#: Chosen so every expected return is exactly representable:
#: 150/100-1 = 0.5, 75/150-1 = -0.5, 150/75-1 = 1.0.
PRICES = np.array([100.0, 150.0, 75.0, 150.0])
DOUBLE_PRICES = np.array([1.0, 2.0, 4.0])
RAMP = np.array([10.0, 20.0, 30.0, 40.0])

# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------


def test_simple_returns_golden_values() -> None:
    np.testing.assert_array_equal(
        simple_returns(PRICES),
        np.array([np.nan, 0.5, -0.5, 1.0]),
    )


def test_log_returns_golden_values() -> None:
    # Doubling each period: ln(2) — expressed as the definition, not by
    # calling the implementation a second time.
    np.testing.assert_allclose(
        log_returns(DOUBLE_PRICES),
        np.array([np.nan, np.log(2.0), np.log(2.0)]),
        rtol=0,
        atol=0,
    )


def test_returns_keep_the_input_length_with_one_documented_nan() -> None:
    for out in (simple_returns(PRICES), log_returns(PRICES)):
        assert out.shape == PRICES.shape
        assert math.isnan(out[0])
        assert np.all(np.isfinite(out[1:]))


def test_returns_have_no_lookahead() -> None:
    longer = np.concatenate([PRICES, [900.0, 12.0, 44.0]])
    np.testing.assert_array_equal(
        simple_returns(PRICES),
        simple_returns(longer)[: PRICES.size],
    )
    np.testing.assert_array_equal(
        log_returns(PRICES),
        log_returns(longer)[: PRICES.size],
    )


def test_returns_reject_a_one_value_series() -> None:
    for fn in (simple_returns, log_returns):
        with pytest.raises(InvalidSeries, match="at least 2 values"):
            fn(np.array([5.0]))


def test_simple_returns_reject_a_zero_price_instead_of_returning_infinity() -> None:
    with pytest.raises(InvalidSeries, match="zero at index 1"):
        simple_returns(np.array([1.0, 0.0, 2.0]))


def test_log_returns_reject_a_non_positive_price() -> None:
    with pytest.raises(InvalidSeries, match="non-positive"):
        log_returns(np.array([1.0, -4.0, 2.0]))


# ---------------------------------------------------------------------------
# Forward labels
# ---------------------------------------------------------------------------


def test_forward_return_golden_values_for_one_and_two_bar_horizons() -> None:
    one = forward_return(PRICES, 1)
    # [150/100-1, 75/150-1, 150/75-1, not-yet-known] = [0.5, -0.5, 1.0, NaN]
    np.testing.assert_array_equal(one, np.array([0.5, -0.5, 1.0, np.nan]))
    two = forward_return(PRICES, 2)
    # [75/100-1, 150/150-1, unknown, unknown] = [-0.25, 0.0, NaN, NaN]
    np.testing.assert_array_equal(two, np.array([-0.25, 0.0, np.nan, np.nan]))


def test_forward_return_tail_is_exactly_the_horizon() -> None:
    out = forward_return(np.arange(1.0, 31.0), horizon=5)
    assert np.all(np.isnan(out[-5:]))
    assert np.all(np.isfinite(out[:-5]))


def test_forward_return_never_revises_a_label_that_was_already_computable() -> None:
    horizon = 3
    before = forward_return(RAMP, horizon)
    longer = np.concatenate([RAMP, [55.0, 66.0, 77.0, 88.0]])
    after = forward_return(longer, horizon)
    known = np.isfinite(before)
    # Positions whose outcome was already observable keep exactly that
    # label; the previously unknown tail may of course become known now
    # that its information exists.
    np.testing.assert_array_equal(before[known], after[: before.size][known])


@pytest.mark.parametrize("horizon", [0, -2, 1.5, True])
def test_forward_return_rejects_bad_horizons(horizon: object) -> None:
    with pytest.raises(InvalidSeries, match="horizon must be"):
        forward_return(PRICES, horizon)  # type: ignore[arg-type]


def test_forward_return_rejects_a_horizon_that_reaches_the_series() -> None:
    with pytest.raises(InvalidSeries, match="longer than"):
        forward_return(PRICES, 6)
    with pytest.raises(InvalidSeries, match="ever be observable"):
        forward_return(PRICES, 4)


def test_forward_return_rejects_a_zero_denominator() -> None:
    with pytest.raises(InvalidSeries, match="zero at index 1"):
        forward_return(np.array([1.0, 0.0, 2.0, 4.0]), horizon=1)


# ---------------------------------------------------------------------------
# Lag
# ---------------------------------------------------------------------------


def test_lag_golden_values() -> None:
    np.testing.assert_array_equal(lag(RAMP, 2), np.array([np.nan, np.nan, 10.0, 20.0]))
    np.testing.assert_array_equal(lag(RAMP, 1), np.array([np.nan, 10.0, 20.0, 30.0]))


def test_lag_has_no_lookahead() -> None:
    longer = np.concatenate([RAMP, [999.0, -5.0, 7.0]])
    np.testing.assert_array_equal(lag(RAMP, 2), lag(longer, 2)[: RAMP.size])


def test_lag_refuses_to_read_the_future() -> None:
    with pytest.raises(InvalidSeries, match="read future values"):
        lag(RAMP, -1)


def test_lag_refuses_a_zero_shift() -> None:
    with pytest.raises(InvalidSeries, match="must be >= 1"):
        lag(RAMP, 0)


def test_lag_rejects_a_non_int_shift_and_one_reaching_the_series() -> None:
    with pytest.raises(InvalidSeries, match="periods must be an int"):
        lag(RAMP, 2.5)  # type: ignore[arg-type]
    with pytest.raises(InvalidSeries, match="must be less than"):
        lag(RAMP, 4)
    with pytest.raises(InvalidSeries, match="longer than"):
        lag(RAMP, 6)


# ---------------------------------------------------------------------------
# Scaling
# ---------------------------------------------------------------------------


def test_scaler_golden_fit_and_transform() -> None:
    scaler = StandardScaler.fit([1.0, 2.0, 3.0, 4.0, 5.0])
    assert scaler.mean == 3.0  # hand: 15 / 5
    assert scaler.std == pytest.approx(math.sqrt(2.0), rel=1e-15)  # variance 10 / 5
    assert scaler.n == 5
    np.testing.assert_allclose(scaler.transform([3.0]), np.array([0.0]), rtol=0, atol=0)
    np.testing.assert_allclose(
        scaler.transform([5.0]),
        np.array([math.sqrt(2.0)]),
        rtol=1e-15,
        atol=0,
    )


def test_scaler_stats_come_from_the_fit_sample_only() -> None:
    train = np.arange(1.0, 11.0)  # mean 5.5
    suffix = np.array([500.0, 900.0])
    scaler = StandardScaler.fit(train)
    assert scaler.mean == float(train.mean())
    assert scaler.n == train.size
    # A fit over the full sample would give a different centre — which is
    # exactly why the fit sample is passed explicitly instead of implied.
    full = StandardScaler.fit(np.concatenate([train, suffix]))
    assert full.mean != scaler.mean


def test_transform_does_not_recentre_on_the_data_being_transformed() -> None:
    scaler = StandardScaler.fit(np.arange(1.0, 11.0))
    transformed = scaler.transform(np.full(50, 100.0))
    expected = (100.0 - scaler.mean) / scaler.std
    np.testing.assert_allclose(transformed, np.full(50, expected), rtol=0, atol=0)
    # Had the scaler (leakily) seen these values it would map them to ~0.
    assert abs(float(transformed.mean())) > 1.0


def test_scaler_is_frozen_once_fitted() -> None:
    scaler = StandardScaler.fit([1.0, 2.0, 3.0])
    with pytest.raises(dataclasses.FrozenInstanceError):
        scaler.mean = 0.0  # type: ignore[misc]


def test_scaler_refuses_a_constant_sample() -> None:
    with pytest.raises(InvalidSeries, match="no spread"):
        StandardScaler.fit([2.0, 2.0, 2.0])


def test_scaler_rejects_invalid_inputs() -> None:
    with pytest.raises(InvalidSeries, match="empty"):
        StandardScaler.fit(np.array([], dtype=np.float64))
    scaler = StandardScaler.fit([1.0, 2.0, 3.0])
    with pytest.raises(InvalidSeries, match=r"non-finite value at index 0"):
        scaler.transform([np.nan, 1.0])


# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------


def test_split_golden_values() -> None:
    split = chronological_split(10, train_fraction=0.8)
    assert isinstance(split, SplitIndices)
    np.testing.assert_array_equal(split.train, np.arange(8))
    np.testing.assert_array_equal(split.test, np.array([8, 9]))
    # int(7 * 0.5) = 3: the cut is truncated, not rounded.
    odd = chronological_split(7, train_fraction=0.5)
    np.testing.assert_array_equal(odd.train, np.array([0, 1, 2]))
    np.testing.assert_array_equal(odd.test, np.array([3, 4, 5, 6]))


@pytest.mark.parametrize(
    ("size", "fraction"),
    [(10, 0.8), (7, 0.5), (100, 0.95), (3, 0.5), (33, 0.04), (100, 0.99)],
)
def test_split_is_disjoint_complete_and_time_ordered(size: int, fraction: float) -> None:
    split = chronological_split(size, train_fraction=fraction)
    # Checked with NumPy directly, not with assert_disjoint (the helper
    # inside the implementation) — this test must not pass itself.
    shared = np.intersect1d(split.train, split.test)
    assert shared.size == 0
    combined = np.concatenate([split.train, split.test])
    np.testing.assert_array_equal(np.sort(combined), np.arange(size))
    assert int(split.train.max()) < int(split.test.min())
    # Deterministic: the same call produces the same fold.
    again = chronological_split(size, train_fraction=fraction)
    np.testing.assert_array_equal(split.train, again.train)
    np.testing.assert_array_equal(split.test, again.test)


def test_assert_disjoint_names_the_shared_index() -> None:
    with pytest.raises(InvalidSeries, match=r"share index 3 "):
        assert_disjoint([1, 2, 3], [3, 4, 5])


def test_assert_disjoint_accepts_separate_and_empty_sets() -> None:
    assert_disjoint([0, 1], [2, 3])
    assert_disjoint(np.array([], dtype=np.int64), [0, 1])


def test_assert_disjoint_rejects_negative_indices() -> None:
    with pytest.raises(InvalidSeries, match="negative index"):
        assert_disjoint([-1, 0], [5])


@pytest.mark.parametrize("fraction", [0.0, 1.0, -0.2, 1.5, float("nan"), float("inf")])
def test_split_rejects_fractions_outside_the_open_unit_interval(fraction: float) -> None:
    with pytest.raises(InvalidSeries, match="strictly between"):
        chronological_split(10, train_fraction=fraction)


def test_split_rejects_a_size_that_cannot_be_split() -> None:
    with pytest.raises(InvalidSeries, match=">= 2"):
        chronological_split(1)
    # bool reaches mypy as an int, so this is a runtime-only refusal:
    # isinstance(True, bool) is caught inside before any arithmetic.
    with pytest.raises(InvalidSeries, match="size must be an int"):
        chronological_split(True)


def test_split_rejects_a_cut_that_would_empty_a_side() -> None:
    with pytest.raises(InvalidSeries, match="empty"):
        chronological_split(4, train_fraction=0.1)


# ---------------------------------------------------------------------------
# Determinism and immutability across the module
# ---------------------------------------------------------------------------


def test_transforms_are_deterministic_and_leave_inputs_alone() -> None:
    prices_before = PRICES.copy()
    ramp_before = RAMP.copy()
    first = [
        simple_returns(PRICES),
        log_returns(PRICES),
        forward_return(PRICES, 1),
        lag(RAMP, 2),
    ]
    second = [
        simple_returns(PRICES),
        log_returns(PRICES),
        forward_return(PRICES, 1),
        lag(RAMP, 2),
    ]
    for a, b in zip(first, second, strict=True):
        np.testing.assert_array_equal(a, b)
    np.testing.assert_array_equal(PRICES, prices_before)
    np.testing.assert_array_equal(RAMP, ramp_before)
