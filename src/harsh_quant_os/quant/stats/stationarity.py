"""Stationarity: the augmented Dickey-Fuller (ADF) unit-root test.

The ADF regression, over a series ``y``::

    Δy_t = c + ψ · y_{t-1} + Σᵢ δᵢ · Δy_{t-i} + ε_t        (i = 1..maxlag)

tests ``H0: ψ = 0`` (the series has a unit root) against the stationary
alternative. The reported statistic is the t-statistic of ``ψ``; the
p-value comes from MacKinnon's response-surface approximation as
implemented by ``statsmodels.tsa.stattools.adfuller``, which is the one
dependency in this repository allowed to compute it — reimplementing a
published approximation would only create a second place to be wrong.

What the ``stationary`` flag means, exactly: the unit-root null was
rejected at ``alpha`` **for this sample**. It is a statement about the
values handed in, not a property of the future and not a trading signal
(the engine does not decide anything — quant-engine.md §1).

Determinism (§3 rule 1): the test is deterministic arithmetic; the same
array returns the same floats, bit for bit, across calls.

Deliberately not here: no differencing, no detrending, no automatic
transformation. Callers transform and record it in their recipe — this
function only reports what it was given.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from statsmodels.tsa.stattools import adfuller

from harsh_quant_os.quant.series import InvalidSeries, as_float_series

__all__ = [
    "Autolag",
    "StationarityResult",
    "adf_stationarity",
]

#: Lag-selection criterion accepted by ``adf_stationarity``.
Autolag = Literal["AIC", "BIC", "t-stat"]

_ALLOWED_AUTOLAG = ("AIC", "BIC", "t-stat")


@dataclass(frozen=True, slots=True)
class StationarityResult:
    """One ADF run, with everything needed to record it in a recipe.

    Attributes:
        statistic: t-statistic of the lagged-level coefficient ψ.
        p_value: MacKinnon approximate p-value for the unit-root null.
        used_lags: Lag order the run actually used.
        n_obs: Observations the run actually used (after trimming).
        alpha: The level this run was asked to judge at.
        stationary: ``p_value < alpha`` — the null was rejected at alpha.
        critical_values: Statistic critical values by level (``"1%"``,
            ``"5%"``, ``"10%"`` for a constant-only regression). Treat as
            read-only.
    """

    statistic: float
    p_value: float
    used_lags: int
    n_obs: int
    alpha: float
    stationary: bool
    critical_values: Mapping[str, float]


def adf_stationarity(
    values: NDArray[np.float64] | Sequence[float],
    *,
    alpha: float = 0.05,
    autolag: Autolag | None = "AIC",
    maxlag: int | None = None,
) -> StationarityResult:
    """Run the Augmented Dickey-Fuller test on a series.

    Args:
        values: The series to test. Must be one-dimensional, non-empty
            and entirely finite — missing data is the caller's decision
            to make and record, not something to compute through.
        alpha: Rejection level for the unit-root null; strictly between
            0 and 1.
        autolag: Lag-selection criterion, or ``None`` to use ``maxlag``
            as given.
        maxlag: Maximum augmented lag order; ``None`` lets statsmodels
            choose its default.

    Returns:
        A :class:`StationarityResult` carrying the statistic, p-value,
        sample sizes, the level, the rejection flag and the critical
        values.

    Raises:
        InvalidSeries: The series is empty, non-1-D or non-finite;
            ``alpha`` is outside (0, 1); ``autolag`` is not one of the
            three accepted spellings or ``None``; ``maxlag`` is not a
            non-negative int; or statsmodels cannot run the test on this
            input (too few observations, singular regression) — its
            reason is preserved in the message.
    """
    x = as_float_series(values, name="values")
    if not (np.isfinite(alpha) and 0.0 < alpha < 1.0):
        raise InvalidSeries(f"alpha must be strictly between 0 and 1, got {alpha!r}")
    if autolag is not None and autolag not in _ALLOWED_AUTOLAG:
        allowed = ", ".join(repr(a) for a in _ALLOWED_AUTOLAG)
        raise InvalidSeries(f"autolag must be one of {allowed} or None, got {autolag!r}")
    if maxlag is not None:
        if isinstance(maxlag, bool) or not isinstance(maxlag, int):
            raise InvalidSeries(f"maxlag must be an int or None, got {type(maxlag).__name__}")
        if maxlag < 0:
            raise InvalidSeries(f"maxlag must be >= 0, got {maxlag}")

    try:
        # With lag selection statsmodels appends the chosen information
        # criterion (6 values); with autolag=None there is none (5 values).
        # The trailing catch-all is deliberate — this module needs the
        # first five either way.
        details = adfuller(
            x,
            maxlag=maxlag,
            autolag=autolag,
            # statsmodels 0.15 warns that the default return will become a
            # result object in 0.16; the plain tuple is this module's
            # contract, so the choice is made explicitly here instead of by
            # default and warning-filter accident.
            result_object=False,
        )
    except (ValueError, np.linalg.LinAlgError) as exc:
        raise InvalidSeries(f"adfuller could not be computed: {exc}") from exc
    statistic, p_value, used_lags, n_obs, critical_values, *_ = details

    p = float(p_value)
    return StationarityResult(
        statistic=float(statistic),
        p_value=p,
        used_lags=int(used_lags),
        n_obs=int(n_obs),
        alpha=alpha,
        stationary=p < alpha,
        critical_values={str(level): float(value) for level, value in critical_values.items()},
    )
