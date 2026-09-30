"""Golden, behavioural and validation tests for ``quant.stats``.

The ADF statistic is cross-checked against an **independently computed**
OLS t-statistic (design matrix built and solved here with NumPy, not via
statsmodels), which is quant-engine.md §3 rule 6's "independently
computed expected value" for a test whose p-value comes from a published
approximation. The two behavioural fixtures are deterministic — a
Park-Miller LCG written out below, never an RNG:

- the raw noise is mean-reverting, so the unit-root null is rejected;
- its cumulative sum is a genuine random walk, so the null is *not*
  rejected at 5%.

Both expectations were observed from the implementation and are
threshold assertions (reject / not reject), not pinned library output.

``acf`` and ``correlation_matrix`` are compared against values worked out
by hand in this file from their documented formulas.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from harsh_quant_os.quant.stats import (
    Autolag,
    InvalidSeries,
    StationarityResult,
    acf,
    adf_stationarity,
    correlation_matrix,
)

pytestmark = pytest.mark.quant


def _park_miller_noise(size: int, *, seed: int = 12345) -> np.ndarray:
    """Deterministic Park-Miller LCG noise in [-0.5, 0.5).

    An explicit arithmetic formula — no RNG, so the fixtures cannot move
    under a generator-version change.
    """
    out = np.empty(size, dtype=np.float64)
    state = seed
    for i in range(size):
        state = (48271 * state) % 2_147_483_647
        out[i] = state / 2_147_483_647.0 - 0.5
    return out


NOISE = _park_miller_noise(300)
WALK = np.cumsum(NOISE)

# ---------------------------------------------------------------------------
# ADF stationarity
# ---------------------------------------------------------------------------


def test_adf_returns_a_typed_result() -> None:
    assert isinstance(adf_stationarity(NOISE), StationarityResult)


def test_adf_rejects_the_unit_root_null_on_mean_reverting_noise() -> None:
    result = adf_stationarity(NOISE)
    assert result.p_value < 0.01
    assert result.stationary is True


def test_adf_does_not_reject_the_null_on_its_random_walk() -> None:
    result = adf_stationarity(WALK)
    assert 0.05 <= result.p_value < 0.5
    assert result.stationary is False


def test_adf_result_fields_are_whole_and_self_consistent() -> None:
    for series in (NOISE, WALK):
        result = adf_stationarity(series)
        assert math.isfinite(result.statistic)
        assert 0.0 <= result.p_value <= 1.0
        assert result.used_lags >= 0
        assert result.n_obs == series.size - result.used_lags - 1
        assert set(result.critical_values) == {"1%", "5%", "10%"}
        # A stricter level must demand a more extreme statistic.
        assert (
            result.critical_values["1%"]
            < result.critical_values["5%"]
            < result.critical_values["10%"]
        )
        assert result.stationary is (result.p_value < result.alpha)


def test_alpha_gates_only_the_flag_not_the_computation() -> None:
    strict = adf_stationarity(WALK, alpha=0.05)
    loose = adf_stationarity(WALK, alpha=0.5)
    assert strict.stationary is False
    assert loose.stationary is True
    # Same series, same test: the number behind the flag never moved.
    assert loose.p_value == strict.p_value
    assert loose.statistic == strict.statistic


def test_adf_statistic_matches_a_hand_rolled_ols_t_statistic() -> None:
    # With maxlag=0 and no lag selection the ADF regression is exactly
    #   Δy_t = c + psi * y_{t-1} + e_t
    # and the statistic is the classical OLS t-statistic of psi. Both the
    # fit and the standard error are computed here from scratch.
    result = adf_stationarity(WALK, maxlag=0, autolag=None)
    differences = np.diff(WALK)
    lagged = WALK[:-1]
    design = np.column_stack([np.ones(lagged.size), lagged])
    beta, *_ = np.linalg.lstsq(design, differences, rcond=None)
    residuals = differences - design @ beta
    rss = float(residuals @ residuals)
    degrees_of_freedom = differences.size - design.shape[1]
    sigma_squared = rss / degrees_of_freedom
    xtx_inverse = np.linalg.inv(design.T @ design)
    standard_error = float(np.sqrt(sigma_squared * xtx_inverse[1, 1]))
    t_statistic = float(beta[1]) / standard_error

    assert result.statistic == pytest.approx(t_statistic, rel=1e-9)
    assert result.used_lags == 0
    assert result.n_obs == WALK.size - 1


@pytest.mark.parametrize("autolag", ["AIC", "BIC", "t-stat", None])
def test_adf_runs_with_every_supported_lag_criterion(autolag: Autolag | None) -> None:
    result = adf_stationarity(NOISE, autolag=autolag)
    assert 0.0 <= result.p_value <= 1.0
    assert result.n_obs <= NOISE.size - 1


def test_adf_is_deterministic_and_leaves_the_input_alone() -> None:
    untouched = WALK.copy()
    first = adf_stationarity(WALK)
    second = adf_stationarity(WALK)
    np.testing.assert_array_equal(WALK, untouched)
    assert first == second


def test_adf_rejects_non_finite_input() -> None:
    bad = NOISE.copy()
    bad[5] = np.nan
    with pytest.raises(InvalidSeries, match=r"non-finite value at index 5"):
        adf_stationarity(bad)


def test_adf_rejects_empty_and_two_dimensional_input() -> None:
    with pytest.raises(InvalidSeries, match="empty"):
        adf_stationarity(np.array([], dtype=np.float64))
    with pytest.raises(InvalidSeries, match="one-dimensional"):
        adf_stationarity(np.ones((4, 2)))


@pytest.mark.parametrize("alpha", [0.0, 1.0, -0.1, 1.5])
def test_adf_rejects_alpha_outside_the_open_unit_interval(alpha: float) -> None:
    with pytest.raises(InvalidSeries, match="strictly between"):
        adf_stationarity(NOISE, alpha=alpha)


def test_adf_rejects_an_unknown_autolag_spelling() -> None:
    with pytest.raises(InvalidSeries, match="autolag must be one of"):
        adf_stationarity(NOISE, autolag="aic")  # type: ignore[arg-type]


def test_adf_rejects_a_bad_maxlag() -> None:
    with pytest.raises(InvalidSeries, match="maxlag must be >= 0"):
        adf_stationarity(NOISE, maxlag=-1)
    with pytest.raises(InvalidSeries, match="maxlag must be an int"):
        adf_stationarity(NOISE, maxlag=2.5)  # type: ignore[arg-type]


def test_adf_wraps_series_statsmodels_cannot_run_with_the_reason() -> None:
    with pytest.raises(InvalidSeries, match="could not be computed"):
        adf_stationarity(np.arange(3.0))
    with pytest.raises(InvalidSeries, match="could not be computed: Invalid input, x is constant"):
        adf_stationarity(np.full(50, 3.0))


# ---------------------------------------------------------------------------
# Autocorrelation
# ---------------------------------------------------------------------------


def test_acf_golden_values_worked_out_by_hand() -> None:
    # x = [1, 2, 3, 4]: mean 2.5, deviations [-1.5, -0.5, 0.5, 1.5],
    # sum of squares 5.0; lag numerators 1.25, -1.5, -2.25
    # -> 1.25/5, -1.5/5, -2.25/5 = 0.25, -0.3, -0.45.
    np.testing.assert_array_equal(
        acf(np.array([1.0, 2.0, 3.0, 4.0]), 3),
        np.array([1.0, 0.25, -0.3, -0.45]),
    )


def test_acf_at_lag_zero_is_exactly_one() -> None:
    out = acf(NOISE, 0)
    assert out.shape == (1,)
    assert out[0] == 1.0


def test_acf_is_deterministic_and_leaves_the_input_alone() -> None:
    untouched = NOISE.copy()
    first = acf(NOISE, 10)
    second = acf(NOISE, 10)
    np.testing.assert_array_equal(NOISE, untouched)
    np.testing.assert_array_equal(first, second)


@pytest.mark.parametrize("nlags", [-1, 2.5, True, "3"])
def test_acf_rejects_bad_lags(nlags: object) -> None:
    with pytest.raises(InvalidSeries, match="nlags must be"):
        acf(NOISE, nlags)  # type: ignore[arg-type]


def test_acf_rejects_a_lag_without_overlapping_pairs() -> None:
    with pytest.raises(InvalidSeries, match="needs at least 301 values"):
        acf(NOISE, 300)


def test_acf_rejects_a_constant_series_instead_of_returning_nan() -> None:
    with pytest.raises(InvalidSeries, match="constant"):
        acf(np.full(10, 2.0), 2)


def test_acf_rejects_empty_two_dimensional_and_non_finite_input() -> None:
    with pytest.raises(InvalidSeries, match="empty"):
        acf(np.array([], dtype=np.float64), 1)
    with pytest.raises(InvalidSeries, match="one-dimensional"):
        acf(np.ones((4, 2)), 1)
    bad = NOISE.copy()
    bad[7] = np.inf
    with pytest.raises(InvalidSeries, match=r"non-finite value at index 7"):
        acf(bad, 1)


# ---------------------------------------------------------------------------
# Correlation matrix
# ---------------------------------------------------------------------------


def test_correlation_matrix_golden_value_worked_out_by_hand() -> None:
    # a = [1,2,3,4], b = [2,1,4,3]: means 2.5/2.5, deviations
    # [-1.5,-0.5,0.5,1.5] and [-0.5,-1.5,1.5,0.5], cross-sum 3.0,
    # sum of squares 5.0 each -> 3 / sqrt(5*5) = 0.6.
    matrix = correlation_matrix(
        [
            np.array([1.0, 2.0, 3.0, 4.0]),
            np.array([2.0, 1.0, 4.0, 3.0]),
        ]
    )
    np.testing.assert_allclose(
        matrix,
        np.array([[1.0, 0.6], [0.6, 1.0]]),
        rtol=1e-12,
        atol=1e-12,
    )


def test_correlation_matrix_perfect_relationships_come_out_as_plus_and_minus_one() -> None:
    a = np.array([1.0, 2.0, 3.0, 4.0])
    rising = correlation_matrix([a, np.array([2.0, 4.0, 6.0, 8.0])])
    falling = correlation_matrix([a, np.array([8.0, 6.0, 4.0, 2.0])])
    assert rising[0, 1] == pytest.approx(1.0, abs=1e-12)
    assert falling[0, 1] == pytest.approx(-1.0, abs=1e-12)


def test_a_single_column_agrees_with_itself_as_a_matrix() -> None:
    matrix = correlation_matrix([NOISE[:20]])
    assert matrix.shape == (1, 1)
    assert matrix[0, 0] == 1.0


def test_matrix_is_symmetric_with_a_unit_diagonal() -> None:
    matrix = correlation_matrix([NOISE, WALK, NOISE * 2.0 + WALK])
    assert matrix.shape == (3, 3)
    np.testing.assert_allclose(matrix, matrix.T, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(np.diag(matrix), np.ones(3), rtol=1e-12, atol=1e-12)


def test_correlation_matrix_is_deterministic_and_leaves_inputs_alone() -> None:
    a = NOISE[:50].copy()
    b = WALK[:50].copy()
    a_untouched = a.copy()
    b_untouched = b.copy()
    first = correlation_matrix([a, b])
    second = correlation_matrix([a, b])
    np.testing.assert_array_equal(first, second)
    np.testing.assert_array_equal(a, a_untouched)
    np.testing.assert_array_equal(b, b_untouched)


def test_correlation_rejects_an_empty_column_list() -> None:
    with pytest.raises(InvalidSeries, match="columns is empty"):
        correlation_matrix([])


def test_correlation_rejects_unequal_lengths_and_names_them() -> None:
    with pytest.raises(InvalidSeries, match="equal length"):
        correlation_matrix([np.ones(5), np.ones(4)])


def test_correlation_rejects_a_single_observation() -> None:
    with pytest.raises(InvalidSeries, match="at least 2 observations"):
        correlation_matrix([np.array([1.0])])


def test_correlation_rejects_a_constant_column_instead_of_returning_nan() -> None:
    with pytest.raises(InvalidSeries, match=r"columns\[1\] is constant"):
        correlation_matrix([NOISE[:20], np.full(20, 4.0)])


def test_correlation_rejects_empty_two_dimensional_and_non_finite_columns() -> None:
    with pytest.raises(InvalidSeries, match=r"columns\[0\] is empty"):
        correlation_matrix([np.array([], dtype=np.float64), np.ones(3)])
    with pytest.raises(InvalidSeries, match="one-dimensional"):
        correlation_matrix([np.ones((2, 2))])
    bad = np.ones(4)
    bad[2] = np.nan
    with pytest.raises(InvalidSeries, match=r"columns\[0\] contains a non-finite value at index 2"):
        correlation_matrix([bad, np.arange(4.0)])
