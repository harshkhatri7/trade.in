"""Scaling: a fitted standardiser whose fit sample is explicit.

quant-engine.md §4 names "scaling on the full sample" as a leakage
risk and controls it by fitting inside the training window only. The
control here is the API itself:

- ``StandardScaler.fit(values)`` computes ``mean``/``std`` from
  **exactly** the values passed — there is no global state, no partial
  fit that remembers earlier data, and nothing is fetched behind the
  caller's back;
- the result is a frozen dataclass: once fitted, the statistics cannot
  be changed, only re-fitted into a new instance;
- ``n`` records how many values the fit saw, so a recipe can state the
  sample it was fitted on instead of leaving it implicit;
- ``transform`` only applies the stored statistics; it never recomputes
  them, so transforming future data cannot re-centre the scaler (the
  mechanical version of this is in ``tests/quant/test_transforms.py``).

A fit over constant values raises: scaling by a zero spread is a
division by zero, not a number.

The engine implements this two-line formula itself rather than pulling
in scikit-learn, whose typed surface this package would then depend on
for one deterministic computation; the stack table in quant-engine.md
§2 keeps scikit-learn for when its heavier transformers are actually
needed. Sample standard deviation uses ``ddof=0``, matching
``quant.indicators.rolling_std``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from harsh_quant_os.quant.series import InvalidSeries, as_float_series

__all__ = ["StandardScaler"]


@dataclass(frozen=True, slots=True)
class StandardScaler:
    """Standardisation statistics fitted on one explicit sample.

    Attributes:
        mean: Arithmetic mean of the fit values.
        std: Population standard deviation (``ddof=0``) of the fit
            values; strictly positive because a zero-spread fit
            refuses.
        n: Number of values the fit saw — part of the record of what
            the scaler was fitted on.
    """

    mean: float
    std: float
    n: int

    @classmethod
    def fit(
        cls,
        values: NDArray[np.float64] | Sequence[float],
    ) -> StandardScaler:
        """Fit statistics on exactly the values passed.

        Args:
            values: The sample to fit on — conventionally the training
                window only. 1-D, finite, non-empty, non-constant.

        Returns:
            A frozen :class:`StandardScaler` holding that sample's
            mean, spread and size.

        Raises:
            InvalidSeries: The sample is empty/non-1-D/non-finite, or
            has zero spread (scaling by it would divide by zero).
        """
        x = as_float_series(values, name="values")
        spread = float(x.std(ddof=0))
        if spread == 0.0:
            raise InvalidSeries("values have no spread; a zero-std scaler would divide by zero")
        return cls(mean=float(x.mean()), std=spread, n=int(x.size))

    def transform(
        self,
        values: NDArray[np.float64] | Sequence[float],
    ) -> NDArray[np.float64]:
        """Apply the fitted statistics to a series without refitting.

        Args:
            values: The series to scale, 1-D, finite, non-empty.

        Returns:
            ``(values - mean) / std`` as float64, same length. The
            result is *not* re-centred on this sample — that would be
            the full-sample leakage this class exists to prevent.

        Raises:
            InvalidSeries: The input series is invalid.
        """
        x = as_float_series(values, name="values")
        return (x - self.mean) / self.std
