"""Hard safety gates for trading activity.

The gate lives in the foundation package on purpose: it must be reachable by
every future component, and it must not depend on strategy code. A strategy
may *request* a trade; the risk engine may reject it; this gate refuses
anything that is not explicitly in paper mode while live trading is disabled.

Live trading is disabled for the whole of Phase 0-15.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from harsh_quant_os.config import Settings


class TradingMode(StrEnum):
    """Execution modes, ordered from least to most dangerous."""

    DISABLED = "disabled"
    PAPER = "paper"
    LIVE = "live"


class TradeGateDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class TradingGateError(RuntimeError):
    """Base class for safety-gate failures."""


class LiveTradingBlockedError(TradingGateError):
    """Raised whenever anything attempts to reach live execution."""


@dataclass(frozen=True, slots=True)
class TradeGateResult:
    """Outcome of a trade-gate evaluation."""

    decision: TradeGateDecision
    mode: TradingMode
    reason: str

    @property
    def approved(self) -> bool:
        return self.decision is TradeGateDecision.APPROVED


def resolve_trading_mode(settings: Settings) -> TradingMode:
    """Return the only execution mode the current configuration permits."""
    if settings.live_trading_enabled:
        # Unreachable through configuration: Settings rejects the flag on load.
        raise LiveTradingBlockedError(
            "LIVE_TRADING_ENABLED is true. Live trading must remain disabled. See SECURITY.md."
        )
    return TradingMode.PAPER if settings.paper_trading_enabled else TradingMode.DISABLED


def assert_live_trading_blocked(settings: Settings) -> None:
    """Raise :class:`LiveTradingBlockedError` if live trading could occur."""
    resolve_trading_mode(settings)


def evaluate_trade_gate(settings: Settings, requested_mode: TradingMode) -> TradeGateResult:
    """Evaluate a trade request against the safety gate.

    The gate is intentionally independent of strategy logic: a strategy can
    ask, and the gate decides.
    """
    if requested_mode is TradingMode.LIVE:
        raise LiveTradingBlockedError(
            "Live execution is not available in this phase of HARSH QUANT OS. "
            "See docs/ROADMAP.md phase 16."
        )

    allowed = resolve_trading_mode(settings)
    if allowed is TradingMode.DISABLED:
        return TradeGateResult(
            decision=TradeGateDecision.REJECTED,
            mode=allowed,
            reason="No trading mode is enabled (paper_trading_enabled=false).",
        )
    if requested_mode is not allowed:
        return TradeGateResult(
            decision=TradeGateDecision.REJECTED,
            mode=allowed,
            reason=f"Requested mode {requested_mode.value!r} does not match allowed mode {allowed.value!r}.",
        )
    return TradeGateResult(
        decision=TradeGateDecision.APPROVED,
        mode=allowed,
        reason="Paper execution only; live trading remains disabled.",
    )
