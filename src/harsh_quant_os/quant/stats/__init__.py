"""Formal statistical properties of a series: stationarity and dependence.

- ``adf_stationarity`` — the augmented Dickey-Fuller unit-root test with
  its full result (statistic, p-value, sample sizes, critical values);
- ``acf`` — the sample autocorrelation function through a requested lag;
- ``correlation_matrix`` — Pearson correlations across equally long
  columns, refusing constant columns instead of returning an undefined
  value.

What is *not* here yet: distribution fitting, cointegration tests, and
any form of automatic transformation — those belong to later Phase 5
increments and are recorded as not implemented until they exist.
"""

from __future__ import annotations

from harsh_quant_os.quant.series import InvalidSeries
from harsh_quant_os.quant.stats.correlation import acf, correlation_matrix
from harsh_quant_os.quant.stats.stationarity import (
    Autolag,
    StationarityResult,
    adf_stationarity,
)

__all__ = [
    "Autolag",
    "InvalidSeries",
    "StationarityResult",
    "acf",
    "adf_stationarity",
    "correlation_matrix",
]
