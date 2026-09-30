"""Exceptions raised by the backtest engine.

Three families, kept apart on purpose:

- Store refusals (:class:`~harsh_quant_os.quant.recipes.recipe.RecipeError`)
  mean "this data, as stored, is not usable" and come from the same
  verification boundary the quant recipes use.
- :class:`BacktestError` means "this backtest input, configuration or
  strategy contract is invalid", and :class:`CausalityViolation` is its
  named subclass for the one invariant the engine treats as sacred: a
  fill must happen strictly after the information that decided it
  (backtesting.md §2 Causality).
- :class:`ReproductionMismatch` is its named subclass for the other
  defect signal: re-executing a recorded manifest produced different
  artefact hashes (backtesting-methodology.md §3 — "treated as a defect
  in the engine or the data — investigated, not explained away").
"""

from __future__ import annotations

__all__ = ["BacktestError", "CausalityViolation", "ReproductionMismatch"]


class BacktestError(Exception):
    """A backtest input, configuration or strategy contract is invalid."""


class CausalityViolation(BacktestError):
    """An order would fill at or before its own decision time.

    Raised, never logged-and-continued: a backtest that processes a
    look-ahead has produced evidence, not results.
    """


class ReproductionMismatch(BacktestError):
    """Re-executing a manifest did not reproduce its recorded artefacts.

    The message names the artefact, the recorded hash and the
    reproduced hash — the whole point of the exception is to say
    *which* number moved.
    """
