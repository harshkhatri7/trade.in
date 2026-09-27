# packages/risk — Risk engine (Phase 9)

Independent risk evaluation: limits, budgets, kill switch and audit records.

**Status: not implemented.** What already exists is the foundation-level
trade gate in `src/harsh_quant_os/safety/`:

- `resolve_trading_mode` — the only mode the configuration permits
- `evaluate_trade_gate` — approves paper, **raises on live**
- `assert_live_trading_blocked` — start-up/sensitive-operation guard

Those are covered by `tests/security/test_live_trading_disabled.py`, which
fails the build if a control is weakened.

Planned controls: position notional, open positions, daily loss, drawdown kill
switch, concentration, order rate, instrument allow-list — each with an
append-only audit record.

Invariant: a strategy may request; risk decides; the gate authorises. There is
no path from a strategy to an order that bypasses risk.

See [docs/architecture/risk-engine.md](../../docs/architecture/risk-engine.md).
