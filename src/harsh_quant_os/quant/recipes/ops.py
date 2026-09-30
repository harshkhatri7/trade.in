"""The feature-operation whitelist recipes may name.

A recipe describes its features as ``{"op": ..., "source": ...,
"params": ...}``; this module is the closed list of names that means
anything, and the function each one maps to. A closed list is the point:
an arbitrary op string from a JSON file never reaches ``eval`` or a
dynamic import, and a recipe written against an op this build does not
have fails validation with the known names listed, instead of silently
producing a different feature than its author meant.

Every function here is one of the golden-tested primitives in
``harsh_quant_os.quant.indicators`` or ``harsh_quant_os.quant.transforms``
— the executor adds no new arithmetic, it only wires sources to
primitives. Parameters are validated by
:meth:`FeatureRecipe.validate <harsh_quant_os.quant.recipes.recipe.FeatureRecipe.validate>`
before any of these run, so ``params[...]`` lookups are guaranteed.

``source`` may name one of :data:`BAR_COLUMNS` or an **earlier** feature
in the same recipe; forward references are refused, which is how the
recipe's execution order stays free of look-ahead by construction.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
from numpy.typing import NDArray

from harsh_quant_os.quant.indicators import ema, rolling_std, rolling_zscore, rsi, sma
from harsh_quant_os.quant.transforms import lag, log_returns, simple_returns

__all__ = ["BAR_COLUMNS", "OPS", "OpSpec"]

#: The input columns every recipe starts from.
BAR_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True, slots=True)
class OpSpec:
    """One whitelisted operation: its name, its parameters, its function."""

    name: str
    params: tuple[str, ...]
    apply: Callable[[NDArray[np.float64], dict[str, int]], NDArray[np.float64]]


def _sma(source: NDArray[np.float64], params: dict[str, int]) -> NDArray[np.float64]:
    return sma(source, params["window"])


def _ema(source: NDArray[np.float64], params: dict[str, int]) -> NDArray[np.float64]:
    return ema(source, params["span"])


def _rolling_std(source: NDArray[np.float64], params: dict[str, int]) -> NDArray[np.float64]:
    return rolling_std(source, params["window"])


def _rolling_zscore(source: NDArray[np.float64], params: dict[str, int]) -> NDArray[np.float64]:
    return rolling_zscore(source, params["window"])


def _rsi(source: NDArray[np.float64], params: dict[str, int]) -> NDArray[np.float64]:
    return rsi(source, params["period"])


def _log_returns(source: NDArray[np.float64], params: dict[str, int]) -> NDArray[np.float64]:
    return log_returns(source)


def _simple_returns(source: NDArray[np.float64], params: dict[str, int]) -> NDArray[np.float64]:
    return simple_returns(source)


def _lag(source: NDArray[np.float64], params: dict[str, int]) -> NDArray[np.float64]:
    return lag(source, params["periods"])


#: ``op`` name → specification. Read-only: a recipe cannot extend it.
OPS: Mapping[str, OpSpec] = MappingProxyType(
    {
        "sma": OpSpec("sma", ("window",), _sma),
        "ema": OpSpec("ema", ("span",), _ema),
        "rolling_std": OpSpec("rolling_std", ("window",), _rolling_std),
        "rolling_zscore": OpSpec("rolling_zscore", ("window",), _rolling_zscore),
        "rsi": OpSpec("rsi", ("period",), _rsi),
        "log_returns": OpSpec("log_returns", (), _log_returns),
        "simple_returns": OpSpec("simple_returns", (), _simple_returns),
        "lag": OpSpec("lag", ("periods",), _lag),
    }
)
