"""The pre-trade risk evaluation contract.

risk-engine.md §1: a strategy can REQUEST a trade, the risk engine can
REJECT it, and a strategy can never override it. The *contract* lives
here in the foundation package so every order path — the backtest
engine now, paper trading later — evaluates risk through the same
type, with no import from strategy code into safety code and none back.

This module holds the verdict type and the evaluator protocol. The
configured evaluator built on ``Settings`` risk limits arrives with the
rest of the risk engine in Phase 9; the backtest engine takes an
evaluator as a required argument (backtesting.md §8 criterion 6 — the
simulated path invokes risk evaluation, and there is no permissive
default it could accidentally run with).

Failure policy (risk-engine.md §6): anything unparseable, out of range
or unrepresentable is a refusal with a reason, never an approval with
a shrug. :meth:`RiskEvaluation.refuse` insists on a stated reason — a
refusal nobody can read is a hidden refusal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

__all__ = ["RiskEvaluation", "RiskEvaluator"]


@dataclass(frozen=True, slots=True)
class RiskEvaluation:
    """The verdict on one order: approved, or refused with a stated reason.

    Attributes:
        approved: Whether the order may proceed.
        reason: The refusal's cause (``""`` when approved).
    """

    approved: bool
    reason: str

    @classmethod
    def allow(cls) -> RiskEvaluation:
        """An approval (reason ``""``)."""
        return cls(approved=True, reason="")

    @classmethod
    def refuse(cls, reason: str) -> RiskEvaluation:
        """A refusal carrying its reason.

        Raises:
            ValueError: An empty or non-string reason — a refusal
            nobody can read is treated as invalid input rather than
            stored. (``ValueError`` on purpose: this foundation module
            imports nothing from the feature packages.)
        """
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("a risk refusal must state its reason")
        return cls(approved=False, reason=reason)


@runtime_checkable
class RiskEvaluator(Protocol):
    """Pre-trade risk evaluation over one order and the state behind it.

    Invoked by the order path for every order, with only state at the
    decision time — a check that read the future would itself be a
    look-ahead. Implementations must be deterministic: the same inputs
    produce the same verdict (a backtest reproduces from its manifest).
    """

    def evaluate(
        self,
        *,
        decision_time: datetime,
        delta: Decimal,
        price: Decimal,
        equity: Decimal,
    ) -> RiskEvaluation:
        """Approve or refuse one order.

        Args:
            decision_time: The information time of the decision
                (timezone-aware bar close).
            delta: Signed quantity change requested (non-zero).
            price: The reference price at decision time.
            equity: Equity marked at decision time.

        Returns:
            :meth:`RiskEvaluation.allow` or
            :meth:`RiskEvaluation.refuse` with a readable reason.
        """
        ...
