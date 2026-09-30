"""The pre-trade risk evaluation contract.

risk-engine.md §1: a strategy can REQUEST a trade, the risk engine can
REJECT it, and a strategy can never override it. The *contract* lives
here in the foundation package so every order path — the backtest
engine now, paper trading later — evaluates risk through the same
type, with no import from strategy code into safety code and none back.

This module holds the verdict type, the evaluator protocol, and
:class:`ConfiguredRiskEvaluator` — the fail-closed evaluator over the
``Settings`` risk limits that the simulated path invokes
(backtesting.md §8 criterion 6). The fuller risk engine — audit
records, rate limits, instrument allow-lists, the drawdown kill switch
— is Phase 9; the contract those pieces plug into is already here.

Failure policy (risk-engine.md §6): anything unparseable, out of range
or unrepresentable is a refusal with a reason, never an approval with
a shrug. :meth:`RiskEvaluation.refuse` insists on a stated reason — a
refusal nobody can read is a hidden refusal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from harsh_quant_os.config import Settings
from harsh_quant_os.safety.gates import assert_live_trading_blocked

__all__ = ["ConfiguredRiskEvaluator", "RiskEvaluation", "RiskEvaluator"]


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
    look-ahead. Implementations must be deterministic over their call
    sequence: a fresh instance walked through the same orders produces
    the same verdicts (a backtest reproduces from its manifest).
    """

    def evaluate(
        self,
        *,
        decision_time: datetime,
        position: Decimal,
        delta: Decimal,
        price: Decimal,
        equity: Decimal,
    ) -> RiskEvaluation:
        """Approve or refuse one order.

        Args:
            decision_time: The information time of the decision
                (timezone-aware bar close).
            position: The signed position the account already holds.
            delta: Signed quantity change requested (non-zero).
            price: The reference price at decision time.
            equity: Equity marked at decision time.

        Returns:
            :meth:`RiskEvaluation.allow` or
            :meth:`RiskEvaluation.refuse` with a readable reason.
        """
        ...


class ConfiguredRiskEvaluator:
    """Fail-closed pre-trade risk over the ``Settings`` limits.

    Three checks, evaluated only for **risk-increasing** orders — an
    order whose resulting position has larger exposure than the
    current one (``|position + delta| > |position|``). Reducing orders
    are always allowed: a risk engine that blocks exits has inverted
    its own purpose (risk-engine.md §1's "the risk engine can REJECT"
    is about taking risk, not about escaping it).

    1. **Position notional** — ``|resulting * price|`` must not exceed
       ``RISK_MAX_POSITION_NOTIONAL``.
    2. **Open positions** — the resulting instrument count must not
       exceed ``RISK_MAX_OPEN_POSITIONS`` (one instrument in this
       engine, and Settings enforces the limit >= 1, so this check
       cannot refuse today; it is implemented anyway so the limit is
       *evaluated*, not skipped, and it becomes binding when
       multi-instrument support arrives).
    3. **Daily loss** — once equity has fallen more than
       ``RISK_MAX_DAILY_LOSS`` below the day's opening mark (the first
       evaluation of each UTC date), risk-increasing orders are refused
       for the rest of that date.

    The constructor runs the live-trading guard first: a configuration
    that claims live trading cannot even build this evaluator.

    Limits are captured once as exact Decimals — floats enter through
    their shortest decimal representation (the number the human
    declared), not a binary approximation.

    State: the day-start equity tracking makes one instance one run's
    companion, the same freshness rule as strategies — construct a new
    evaluator per backtest and identical call sequences give identical
    verdicts.

    Unparseable inputs (non-finite, non-exact, naive timestamps) are
    **refusals with reasons**, per risk-engine.md §6's failure policy —
    the check that cannot understand its input cannot approve what it
    does not understand.
    """

    def __init__(self, settings: Settings) -> None:
        assert_live_trading_blocked(settings)
        notional = Decimal(str(settings.risk_max_position_notional))
        daily_loss = Decimal(str(settings.risk_max_daily_loss))
        open_positions = int(settings.risk_max_open_positions)
        if not notional.is_finite() or notional <= 0:
            raise ValueError(
                "RISK_MAX_POSITION_NOTIONAL must be positive, got "
                f"{settings.risk_max_position_notional!r}"
            )
        if not daily_loss.is_finite() or daily_loss <= 0:
            raise ValueError(
                f"RISK_MAX_DAILY_LOSS must be positive, got {settings.risk_max_daily_loss!r}"
            )
        if open_positions < 1:
            raise ValueError(
                f"RISK_MAX_OPEN_POSITIONS must be at least 1, got "
                f"{settings.risk_max_open_positions!r}"
            )
        self._max_position_notional = notional
        self._max_daily_loss = daily_loss
        self._max_open_positions = open_positions
        self._day: date | None = None
        self._day_start_equity: Decimal | None = None

    def limits(self) -> dict[str, str]:
        """The captured limits as exact strings, for the run manifest.

        Keyed by the shortened names of the Settings fields they came
        from, values stringified from the exact Decimals actually
        enforced — so a manifest records the limits that decided the
        run, not the floats that were declared.
        """
        return {
            "max_daily_loss": str(self._max_daily_loss),
            "max_open_positions": str(self._max_open_positions),
            "max_position_notional": str(self._max_position_notional),
        }

    def evaluate(
        self,
        *,
        decision_time: datetime,
        position: Decimal,
        delta: Decimal,
        price: Decimal,
        equity: Decimal,
    ) -> RiskEvaluation:
        """Approve or refuse one order against the configured limits.

        Raises nothing for bad inputs: an input this check cannot
        parse is a refusal naming what was wrong (§6's failure policy).
        """
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            return RiskEvaluation.refuse(
                f"unparseable decision_time: naive timestamp {decision_time!r}; "
                "risk evaluation needs timezone-aware time (risk-engine.md section 6)"
            )
        exact: dict[str, object] = {
            "position": position,
            "delta": delta,
            "price": price,
            "equity": equity,
        }
        for field, raw in exact.items():
            if isinstance(raw, bool) or not isinstance(raw, (Decimal, int)):
                return RiskEvaluation.refuse(
                    f"unparseable {field}: {type(raw).__name__} {raw!r}; exact "
                    "Decimal inputs only (risk-engine.md section 6)"
                )
            if not Decimal(raw).is_finite():
                return RiskEvaluation.refuse(
                    f"unparseable {field}: non-finite value {raw!r} (risk-engine.md section 6)"
                )

        resulting = position + delta
        if abs(resulting) <= abs(position):
            return RiskEvaluation.allow()  # reducing: never blocked

        # Day tracking: the first evaluation of each UTC date establishes
        # the mark the day's loss is measured from.
        day = decision_time.astimezone(UTC).date()
        if self._day != day or self._day_start_equity is None:
            self._day = day
            self._day_start_equity = equity

        loss = self._day_start_equity - equity
        if loss > self._max_daily_loss:
            return RiskEvaluation.refuse(
                f"daily loss {loss} exceeds RISK_MAX_DAILY_LOSS "
                f"{self._max_daily_loss} (day opened at equity "
                f"{self._day_start_equity})"
            )

        order_notional = abs(resulting * price)
        if order_notional > self._max_position_notional:
            return RiskEvaluation.refuse(
                f"resulting position notional {order_notional} exceeds "
                f"RISK_MAX_POSITION_NOTIONAL {self._max_position_notional} "
                f"(position {position} + delta {delta} at price {price})"
            )

        resulting_open = 1 if resulting != 0 else 0
        if resulting_open > self._max_open_positions:
            return RiskEvaluation.refuse(
                f"open positions {resulting_open} would exceed "
                f"RISK_MAX_OPEN_POSITIONS {self._max_open_positions}"
            )

        return RiskEvaluation.allow()
