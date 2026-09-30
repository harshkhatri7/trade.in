# Risk engine architecture

**Phase:** 0 — Foundation, extended in Phase 6 with the pre-trade risk
evaluation seam (`safety/risk.py`). The **trade gate** exists and is
tested; the full risk engine is Phase 9.

---

## 1. The invariant

```text
A strategy can REQUEST a trade.
The risk engine can REJECT it.
A strategy can NEVER override the risk engine.
The trade gate is the last authority, and it refuses live execution outright.
```

This is enforced in two independent ways:

1. **Architecturally** — strategy code has no import path to order execution;
   everything passes through `harsh_quant_os.safety.gates`.
2. **By test** — `tests/security/test_live_trading_disabled.py` fails the
   build if a gate is weakened.

---

## 2. What exists in Phase 0

`src/harsh_quant_os/safety/gates.py`:

| Symbol                      | Behaviour                                                       |
| --------------------------- | --------------------------------------------------------------- |
| `TradingMode`               | `disabled` \| `paper` \| `live`                                  |
| `resolve_trading_mode()`    | Returns the only mode the configuration permits; raises if live is somehow set |
| `evaluate_trade_gate()`     | Approves/rejects a requested mode; raises on any `live` request  |
| `assert_live_trading_blocked()` | Convenience guard used at start-up and before sensitive operations |
| `LiveTradingBlockedError`  | The exception raised whenever live execution is attempted        |

Configuration support in `Settings`:

- `LIVE_TRADING_ENABLED=true` is rejected at load time;
- `PAPER_TRADING_ENABLED` defaults to `false` — nothing trades by default;
- risk defaults (`RISK_MAX_POSITION_NOTIONAL`, `RISK_MAX_DAILY_LOSS`,
  `RISK_MAX_OPEN_POSITIONS`, `RISK_DRAWDOWN_KILL_SWITCH_PERCENT`) are typed
  and validated, ready for Phase 9.

`src/harsh_quant_os/safety/risk.py` — the pre-trade evaluation seam,
added in Phase 6 so the backtest engine's simulated path invokes risk
evaluation for every order (backtesting.md §8 criterion 6):

- `RiskEvaluation` — the verdict type; a refusal must state its reason.
- `RiskEvaluator` — the protocol every order path evaluates through.
- `ConfiguredRiskEvaluator` — fail-closed over three of the four
  Settings limits: position notional; open positions (evaluated, but a
  single-instrument engine and the validated `>= 1` floor mean it
  cannot refuse today — implemented so the limit is evaluated, not
  skipped); and daily loss (per UTC date, measured from the first
  evaluation of that date). Risk-*reducing* orders are never blocked,
  and unparseable inputs refuse with the reason. The constructor runs
  the live-trading guard first, so a configuration claiming live
  trading cannot even build it. Limits are captured as exact decimals.
  One instance is one run's companion (day-start tracking), the same
  freshness rule as strategies. The drawdown kill switch, audit
  records, rate limits and instrument allow-lists remain Phase 9.

Test coverage: gate approval/rejection paths, the live-request refusal,
the forced-flag scenario, the configuration load rejection — and for
the evaluator, construction under a live flag, limit refusals naming
both numbers, the daily-loss cycle across dates, reducing orders that
are never blocked, and unparseable inputs refused with reasons
(`tests/security/test_risk_evaluation.py`).

---

## 3. Phase 9 — the risk engine

Independent of strategy logic, with its own configuration, its own tests and
its own audit trail.

| Control                     | Type        | Behaviour                                              |
| --------------------------- | ----------- | ------------------------------------------------------ |
| Max position notional       | Limit       | Rejects orders exceeding per-instrument notional        |
| Max open positions          | Limit       | Rejects when the count is already reached               |
| Max daily loss              | Limit       | Stops new risk for the day                              |
| Drawdown kill switch        | Circuit breaker | Halts all new risk until human reset                |
| Concentration limits        | Limit       | Sector/issuer caps                                      |
| Order rate limit            | Limit       | Rejects bursts (fat-finger protection)                  |
| Instrument allow-list       | Precondition| Only instruments explicitly approved                    |
| Trading mode gate           | Precondition| Paper only until Phase 16                               |

Every decision — approved or rejected — produces an **append-only audit
record** with: request id, strategy id, evaluated rules, result, reason,
timestamp, and the risk configuration version used.

---

## 4. Independence rules

- The risk engine never imports strategy code.
- Risk configuration is versioned; a decision records the version used.
- No strategy, backtest, AI agent or operator API may widen a limit at run
  time. Widening a limit is a reviewed configuration change, recorded as
  such.
- The AI layer has **no** access to risk configuration at all.
- The kill switch can only be reset by a human action, and the reset is
  audited.

---

## 5. Order flow

```text
STRATEGY ──► signal ──► RISK ENGINE ──► approved? ──► TRADE GATE ──► PAPER
                             │                            │
                             │ rejected                   │ rejected
                             ▼                            ▼
                        audit record                 audit record
                             │
                             └──► strategy is informed; it cannot retry past the gate
```

In Phase 16 the gate additionally requires a human approval record before any
`live` request could even be considered. That path does not exist today.

---

## 6. Failure policy

Risk failures **fail closed**:

- if the risk engine is unavailable, no orders are approved;
- if configuration is invalid, start-up aborts;
- if an audit write fails, the trade is not submitted;
- if a limit cannot be evaluated, the answer is "reject".

---

## 7. Current state and exit criteria

**Phase 0:** trade gate implemented and tested; risk limits present as
validated configuration; no runtime risk engine.

**Phase 9 exit criteria:**

- All controls above implemented with property tests.
- A test proves a strategy cannot reach execution while bypassing risk.
- Removing any control fails the test suite.
- Audit records are append-only and queryable.
- Kill switch behaviour verified end to end.
