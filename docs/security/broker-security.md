# Broker security

**Status:** no broker is connected. No broker SDK, endpoint or credential
exists anywhere in this repository.

Broker work is scheduled for **Phase 15 (research only)** and **Phase 16
(controlled live trading)**. This document records the constraints those
phases must satisfy, so nobody designs around them later.

---

## 1. Standing rules

1. Phase 15 produces a **design review**, not code that places orders.
2. Phase 16 requires: completed risk engine (Phase 9), paper-trading evidence
   (Phase 10), security review, and explicit human approval records.
3. Nothing in Phases 0–14 may add a broker client, a broker URL call, or a
   broker credential field that is ever populated.
4. `Settings` rejects `LIVE_TRADING_ENABLED=true` today. Removing that check
   is a deliberate, reviewed, Phase-16-only change — and it must be replaced
   by a strictly stronger control, never a weaker one.

---

## 2. Credential requirements (Phase 15/16 design)

| Requirement                          | Detail                                                     |
| ------------------------------------ | ---------------------------------------------------------- |
| Storage                              | Dedicated secret store or platform vault — **not** `.env` in the repo |
| Access                               | Readable only by the execution service, never by AI, web or quant code |
| Scope                                | Least privilege: read-only keys until an order is required |
| IP allow-listing                     | Where the broker supports it, restrict to the egress IP    |
| Rotation                             | Documented, rehearsed, with a tested revocation path       |
| Split                                | Separate keys per environment; no shared production key    |
| MFA                                  | Enabled on the broker account itself                       |
| Dual control                         | Two people required to change a key or widen a limit        |

---

## 3. Execution controls (Phase 16)

- Orders pass **risk engine → trade gate → human approval** in that order.
- Hard caps: per-order notional, per-day loss, open positions, symbol
  allow-list.
- A kill switch that halts new orders immediately and is reset only by a
  human, with the reset audited.
- Idempotency keys on every submission so a retry cannot double-fill.
- Reconciliation against the broker's own state after every session; a
  mismatch stops trading.
- Every submission, rejection, fill and error recorded in the append-only
  audit log.

---

## 4. Failure modes to design against

| Failure                    | Required behaviour                                    |
| -------------------------- | ------------------------------------------------------ |
| Partial fill               | Position state reconciled; no phantom size            |
| Duplicated submission      | Prevented by idempotency key                          |
| Network drop mid-order     | Query state before any retry                          |
| Broker rejects             | Typed error, audit entry, no blind retry loop         |
| Broker outage              | Stop submitting; report; do not assume success        |
| Clock skew                 | Exchange time used for sequencing, not local time     |
| Key leaked                 | Revoke immediately, halt trading, investigate         |

---

## 5. Prohibited, permanently

- Sending credentials to any component other than the execution service.
- Logging order credentials or account identifiers.
- Storing broker keys in the repository, in a notebook, or in a chat log.
- Allowing an AI agent to hold broker credentials or call an execution tool.
- Allowing a strategy to widen a risk limit or bypass the gate.
- Automatic live trading without an auditable human approval.

---

## 6. Current reality check

| Question                                   | Answer        |
| ------------------------------------------ | ------------- |
| Is a broker connected?                     | **No**        |
| Are there broker credentials in the repo?  | **No** (verified by the secret scan) |
| Can any code path place a live order?      | **No**        |
| Is Phase 15 started?                       | **No**        |
| Is Phase 16 started?                       | **No**        |

These answers are re-verified by `tests/security/` on every run.

See [threat model](threat-model.md) and
[risk engine](../architecture/risk-engine.md).
