"""Deflated Sharpe: the headline prices how many shots were taken.

anti-overfitting.md §2.5: "Record every variant attempted. Apply
deflated performance measures so the headline number accounts for how
many shots were taken."

The recording side already exists: :class:`SelectionTrace`
(validation.py) keeps every variant in ``runs`` and states that the
multiple-testing count is ``len(runs)``, "not a secret". This module
is the measuring side — one figure that carries the count instead of
pretending the winning run was the only attempt.

The model (Bailey & López de Prado, *The Deflated Sharpe Ratio*,
2014), stated so a reader can check the arithmetic:

- **SR** — mean/std of the per-period returns (here: the per-bar
  equity returns, the series :func:`compute_metrics` builds for
  ``VolatilityStats``), in **per-period units**. ``VolatilityStats``
  reports this figure times ``sqrt(bar frequency)``; the deflation
  formula is stated per-period, so no annualisation enters it.
  Moments are population (ddof=0), the quant package's convention.
- **V[SR]** — ``(1 - skew*SR + (kurt - 1)/4 * SR^2) / (T - 1)``, the
  estimator's variance when the returns are iid normal draws;
  ``kurt`` is Pearson (3 for a normal), ``T`` the period count.
- **SR0** — ``sqrt(V[SR])`` times the expected maximum of ``trials``
  standard normals (Blom's estimate), i.e. how far the best of
  ``trials`` no-skill shots would typically get, in the same units.
- **deflated** — ``Φ((SR - SR0) / sqrt(V[SR]))``: the normal-model
  probability that the best of those ``trials`` no-skill shots would
  fall short of the observed SR.

Precision: statistical ``float`` arithmetic via ``statistics.NormalDist``
(no new dependency, no numpy), like the quant package — money never
leaves ``Decimal``. The assumptions are part of the figure: iid normal
shots, and a trial count that is complete because it was recorded.
An undercounted count inflates the number, so the count is a record
claim, and the note carried beside the figure says what it is not.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import NormalDist

from harsh_quant_os.backtesting.engine import BacktestResult
from harsh_quant_os.backtesting.errors import BacktestError

__all__ = ["DeflatedSharpe", "deflated_from_result", "deflated_sharpe"]

#: Euler-Mascheroni, for Blom's estimate of the expected maximum.
_EULER_GAMMA = 0.5772156649015328606

#: What the figure is and is not — carried by every report.
_NOTE = (
    "deflated is the normal-model probability that the best of the "
    "recorded shots, drawn from a no-skill null, would fall short of "
    "this per-period Sharpe: it prices how many shots were taken "
    "(anti-overfitting section 2.5), assuming the shots behave as iid "
    "normal draws and that the recorded count is complete. It is not "
    "the probability that the strategy works, not a forecast, and an "
    "undercounted trials number inflates it."
)


def _expected_max(trials: int) -> float:
    """Expected maximum of ``trials`` standard normals (Blom's estimate).

    One shot has an expected maximum of exactly 0 (the draw's own
    mean); the formula's Blom weights apply from two shots on.
    """
    if trials == 1:
        return 0.0
    normal = NormalDist()
    gamma = _EULER_GAMMA
    return (1 - gamma) * normal.inv_cdf(1 - 1 / trials) + gamma * normal.inv_cdf(
        1 - 1 / (trials * math.e)
    )


@dataclass(frozen=True, slots=True)
class DeflatedSharpe:
    """One deflated headline: the observed SR beside the best-of-N null.

    Attributes:
        sharpe: Observed per-period Sharpe (mean/std of the per-bar
            equity returns, population moments, ddof=0). Per-period
            units: the report's annualised Sharpe is this times
            ``sqrt(bar frequency)``.
        sr_variance: ``V[SR]`` — the estimator's variance under the
            iid-normal model; positive or the figure is refused.
        null_expected_max: ``SR0`` — what the best of ``trials``
            no-skill shots is expected to reach, same units.
        deflated: ``Φ((SR - SR0) / sqrt(V[SR]))``, within [0, 1].
        trials: The recorded shot count (``SelectionTrace``:
            ``len(runs)``).
        periods: How many returns the estimate stands on.
        skewness: Population third standard moment of the returns.
        kurtosis: Population Pearson kurtosis (3 for a normal).
        note: The honesty note carried with the numbers.

    Raises:
        BacktestError: A shot count or period count below its floor, a
        non-finite figure, a non-positive variance, a deflated value
        outside [0, 1], an empty note, or a figure that cannot account
        for itself — the null expectation must be
        ``sqrt(V[SR]) * expected max of trials`` and the deflated value
        must be the normal CDF of the stated spread, both re-derived
        here rather than trusted.
    """

    sharpe: float
    sr_variance: float
    null_expected_max: float
    deflated: float
    trials: int
    periods: int
    skewness: float
    kurtosis: float
    note: str

    def __post_init__(self) -> None:
        raw_trials: object = self.trials
        if isinstance(raw_trials, bool) or not isinstance(raw_trials, int):
            raise BacktestError(
                "a deflated headline records its shot count as an int, got "
                f"{type(raw_trials).__name__}"
            )
        if self.trials < 1:
            raise BacktestError(
                f"a deflated headline stands on at least one recorded shot, "
                f"got {self.trials}: the count is what deflates the headline "
                "and it cannot be zero"
            )
        if self.periods < 2:
            raise BacktestError(
                f"a deflated headline stands on at least two periods, got "
                f"{self.periods}: one observation carries no dispersion"
            )
        for name, value in (
            ("sharpe", self.sharpe),
            ("sr_variance", self.sr_variance),
            ("null_expected_max", self.null_expected_max),
            ("skewness", self.skewness),
            ("kurtosis", self.kurtosis),
        ):
            raw: object = value
            if not isinstance(raw, float) or not math.isfinite(raw):
                raise BacktestError(
                    f"the deflated headline's {name} must be a finite float, got {value!r}"
                )
        if not self.sr_variance > 0:
            raise BacktestError(
                f"the Sharpe estimator's variance is {self.sr_variance}: "
                "without a positive variance there is nothing to deflate "
                "against, and the figure is refused rather than smoothed"
            )
        if not 0.0 <= self.deflated <= 1.0:
            raise BacktestError(f"the deflated Sharpe must lie within [0, 1], got {self.deflated}")
        if not self.note.strip():
            raise BacktestError(
                "a deflated headline carries its note: the number alone overstates what it means"
            )

        expected = _expected_max(self.trials)
        null_max = math.sqrt(self.sr_variance) * expected
        if null_max != self.null_expected_max:
            raise BacktestError(
                f"the headline records best-of-{self.trials} expectation "
                f"{self.null_expected_max} but sqrt({self.sr_variance}) * "
                f"{expected} is {null_max}: a headline that cannot account "
                "for its own null expectation is refused"
            )
        deflated = NormalDist().cdf(
            (self.sharpe - self.null_expected_max) / math.sqrt(self.sr_variance)
        )
        if deflated != self.deflated:
            raise BacktestError(
                f"the headline records deflated {self.deflated} but "
                f"Phi(({self.sharpe} - {self.null_expected_max}) / "
                f"sqrt({self.sr_variance})) = {deflated}: a headline that "
                "cannot account for itself is refused"
            )

    @property
    def shots_text(self) -> str:
        """The count in words — the plural the report prints."""
        return "shot" if self.trials == 1 else "shots"


def deflated_sharpe(returns: Sequence[Decimal], *, trials: int) -> DeflatedSharpe:
    """Deflate a per-period return series by the recorded shot count.

    Args:
        returns: Per-period net returns as exact ``Decimal`` (the
            equity curve's ``e[t] / e[t-1] - 1``, or any declared
            series). Converted to ``float`` for the statistics — money
            never leaves ``Decimal`` on the way in.
        trials: How many variants were tried — ``len(trace.runs)`` from
            a :class:`SelectionTrace`, or the honest count of every
            attempt (anti-overfitting §2.5). Explicit: there is no
            default shot count, because a default would be a guess
            wearing a number's clothes.

    Returns:
        The deflated headline with its note attached.

    Raises:
        BacktestError: A shot count that is not a positive int, fewer
        than two periods, a return that is not a finite ``Decimal`` (or
        does not survive the float conversion), a flat series (no
        dispersion to stand on), moments that overflow the float the
        statistics run on, or a non-positive Sharpe-estimator variance.
    """
    raw_trials: object = trials
    if isinstance(raw_trials, bool) or not isinstance(raw_trials, int):
        raise BacktestError(
            "the shot count must be an int recorded beside the result, got "
            f"{type(raw_trials).__name__} (anti-overfitting section 2.5)"
        )
    if trials < 1:
        raise BacktestError(
            f"a deflated headline stands on at least one recorded shot, got "
            f"{trials}: a null that counted no attempts cannot deflate one"
        )
    if len(returns) < 2:
        raise BacktestError(
            f"deflating needs at least two periods, got {len(returns)}: one "
            "observation carries no dispersion"
        )

    series: list[float] = []
    for index, value in enumerate(returns):
        raw: object = value
        if not isinstance(raw, Decimal):
            raise BacktestError(
                f"return {index} is {type(raw).__name__}, not a Decimal: a "
                "series that is not exact numerics is refused rather than "
                "coerced"
            )
        if not raw.is_finite():
            raise BacktestError(
                f"return {index} is {raw}: every period must be finite, and "
                "a non-finite one is refused rather than dropped"
            )
        number = float(raw)
        if not math.isfinite(number):
            raise BacktestError(
                f"return {index} ({raw}) does not survive conversion to the "
                "float the statistics run on"
            )
        series.append(number)

    count = len(series)
    mean = math.fsum(series) / count
    variance = math.fsum((value - mean) ** 2 for value in series) / count
    if variance <= 0.0:
        raise BacktestError(
            "per-period returns have no variation over this sample: a Sharpe "
            "has no dispersion to stand on, so nothing can be deflated — "
            "refused rather than reported as infinity"
        )
    sigma = math.sqrt(variance)
    third = math.fsum((value - mean) ** 3 for value in series) / count
    fourth = math.fsum((value - mean) ** 4 for value in series) / count
    skewness = third / (variance * sigma)
    kurtosis = fourth / (variance * variance)
    sharpe = mean / sigma
    sr_variance = (1.0 - skewness * sharpe + (kurtosis - 1.0) / 4.0 * sharpe * sharpe) / (count - 1)

    for name, figure in (
        ("skewness", skewness),
        ("kurtosis", kurtosis),
        ("the Sharpe", sharpe),
        ("the Sharpe estimator's variance", sr_variance),
    ):
        if not math.isfinite(figure):
            raise BacktestError(
                f"{name} came out non-finite for this series: the moments "
                "overflowed the float the statistics run on, and an "
                "overflowed deflation is refused rather than reported"
            )
    if sr_variance <= 0.0:
        raise BacktestError(
            f"the Sharpe estimator's variance came out {sr_variance} for "
            "this series: without a positive variance there is nothing to "
            "deflate against, and the figure is refused"
        )

    sqrt_variance = math.sqrt(sr_variance)
    null_max = sqrt_variance * _expected_max(trials)
    deflated = NormalDist().cdf((sharpe - null_max) / sqrt_variance)

    return DeflatedSharpe(
        sharpe=sharpe,
        sr_variance=sr_variance,
        null_expected_max=null_max,
        deflated=deflated,
        trials=trials,
        periods=count,
        skewness=skewness,
        kurtosis=kurtosis,
        note=_NOTE,
    )


def deflated_from_result(result: BacktestResult, *, trials: int) -> DeflatedSharpe:
    """Deflate the run's own equity returns — the VolatilityStats series.

    Args:
        result: The recorded run; its per-bar equity returns
            (``e[t] / e[t-1] - 1``) are the series, the same basis
            ``compute_metrics`` uses for ``VolatilityStats``.
        trials: The recorded shot count (see
            :func:`deflated_sharpe`).

    Returns:
        The deflated headline with its note attached.

    Raises:
        BacktestError: Fewer than two equity points, a non-positive
        equity point (a ratio return over a non-positive account is
        undefined — stated rather than reported as a number), or any
        refusal from :func:`deflated_sharpe`.
    """
    curve = result.equity_curve
    if len(curve) < 2:
        raise BacktestError(f"deflating needs at least two equity points, got {len(curve)}")
    for point in curve:
        if point.equity <= 0:
            raise BacktestError(
                f"equity is {point.equity} at {point.time.isoformat()}: a "
                "ratio return over a non-positive account is undefined, and "
                "this refusal is stated rather than reported as a number"
            )
    returns = [curve[index].equity / curve[index - 1].equity - 1 for index in range(1, len(curve))]
    return deflated_sharpe(returns, trials=trials)
