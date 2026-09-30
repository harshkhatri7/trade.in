"""Exceptions raised by the backtest engine.

Two families, kept apart on purpose:

- Store refusals (:class:`~harsh_quant_os.quant.recipes.recipe.RecipeError`)
  mean "this data, as stored, is not usable" and come from the same
  verification boundary the quant recipes use.
- :class:`BacktestError` means "this backtest input, configuration or
  strategy contract is invalid", and :class:`CausalityViolation` is its
  named subclass for the one invariant the engine treats as sacred: a
  fill must happen strictly after the information that decided it
  (backtesting.md §2 Causality).
"""

from __future__ import annotations

__all__ = ["BacktestError", "CausalityViolation"]


class BacktestError(Exception):
    """A backtest input, configuration or strategy contract is invalid."""


class CausalityViolation(BacktestError):
    """An order would fill at or before its own decision time.

    Raised, never logged-and-continued: a backtest that processes a
    look-ahead has produced evidence, not results.
    """
