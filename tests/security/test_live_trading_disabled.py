"""Safety-gate tests: live trading must be unreachable in every code path."""

from __future__ import annotations

import pytest

from harsh_quant_os.config import Settings
from harsh_quant_os.safety import (
    LiveTradingBlockedError,
    TradeGateDecision,
    assert_live_trading_blocked,
    evaluate_trade_gate,
    resolve_trading_mode,
)
from harsh_quant_os.safety import TradingMode as TradingModeEnum


@pytest.mark.security
@pytest.mark.unit
def test_default_mode_is_disabled() -> None:
    assert resolve_trading_mode(Settings.load(_env_file=None)) is TradingModeEnum.DISABLED


@pytest.mark.security
@pytest.mark.unit
def test_paper_mode_when_paper_enabled() -> None:
    settings = Settings.load(_env_file=None, paper_trading_enabled=True)

    assert resolve_trading_mode(settings) is TradingModeEnum.PAPER


@pytest.mark.security
@pytest.mark.unit
def test_live_mode_is_impossible() -> None:
    """Even if a caller forces the flag past validation, the gate blocks it."""
    settings = Settings.model_construct(live_trading_enabled=True)

    assert settings.live_trading_enabled is True

    with pytest.raises(LiveTradingBlockedError):
        resolve_trading_mode(settings)

    with pytest.raises(LiveTradingBlockedError):
        assert_live_trading_blocked(settings)


@pytest.mark.security
@pytest.mark.unit
def test_requesting_live_execution_raises() -> None:
    settings = Settings.load(_env_file=None, paper_trading_enabled=True)

    with pytest.raises(LiveTradingBlockedError, match="not available in this phase"):
        evaluate_trade_gate(settings, TradingModeEnum.LIVE)


@pytest.mark.security
@pytest.mark.unit
def test_gate_rejects_when_nothing_enabled() -> None:
    result = evaluate_trade_gate(Settings.load(_env_file=None), TradingModeEnum.PAPER)

    assert result.decision is TradeGateDecision.REJECTED
    assert result.approved is False
    assert "paper_trading_enabled=false" in result.reason


@pytest.mark.security
@pytest.mark.unit
def test_gate_rejects_paper_when_only_disabled_allowed() -> None:
    settings = Settings.load(_env_file=None, paper_trading_enabled=False)

    assert evaluate_trade_gate(settings, TradingModeEnum.PAPER).approved is False


@pytest.mark.security
@pytest.mark.unit
def test_gate_approves_paper_request_in_paper_mode() -> None:
    settings = Settings.load(_env_file=None, paper_trading_enabled=True)

    result = evaluate_trade_gate(settings, TradingModeEnum.PAPER)

    assert result.decision is TradeGateDecision.APPROVED
    assert result.mode is TradingModeEnum.PAPER
    assert "live trading remains disabled" in result.reason
