# Local agent architecture

**Phase:** 0 — Foundation. **The agent is not implemented (Phase 11).** The
job contract it will speak is implemented and tested today.

---

## 1. Why it exists

Some work belongs on the researcher's PC: large datasets, long backtests,
ML training, local models. The web application must be able to request that
work **without ever gaining access to the filesystem**.

```text
WEB / API ──authenticated job──► LOCAL AGENT ──allow-listed paths──► LOCAL COMPUTE
```

The browser never talks to the agent. The agent never exposes a shell.

---

## 2. Trust model

| Property                | Mechanism                                                        |
| ----------------------- | ---------------------------------------------------------------- |
| Authentication          | Shared token issued by the API (`LOCAL_AGENT_TOKEN`), rotated regularly |
| Authorisation           | Job carries an authenticated principal and an operation name      |
| Operation allow-list    | `JobOperation` enum; anything else is rejected at parse time      |
| Path allow-list         | Per-job `allowed_roots`; an empty list means **no** access        |
| Job identity            | Server-generated `job_id` (UUID); status transitions are checked  |
| Resource limits         | Concurrency, timeout, and memory/CPU ceilings                     |
| Cancellation            | Client may request cancellation; agent terminates the job cleanly |
| Audit                   | Append-only record per job: who, what, when, result, error        |
| Transport               | Localhost by default; token required on every request             |
| Filesystem              | Only paths under `allowed_roots`; canonicalised and prefix-checked |
| Shell                   | Never available. Operations are typed functions, not commands     |

---

## 3. Job contract (implemented in Phase 0)

`harsh_quant_os.contracts.jobs.LocalAgentJob`:

```text
job_id        UUID, server generated
operation     JobOperation  (dataset.scan | dataset.build_features |
                             backtest.run | model.train)
requested_by  authenticated principal, never empty
allowed_roots tuple of absolute paths; empty = no access
status        queued → running → succeeded | failed | cancelled
created_at / started_at / finished_at   (timezone aware)
timeout_seconds   bounded
error         populated only on failure
```

Validation rules already enforced:

- `allowed_roots` entries must be non-empty;
- unknown fields are rejected (`extra="forbid"`);
- `is_terminal` is derived, not settable by a client.

The TypeScript mirror lives in `@harsh-quant-os/types` and is kept in sync by
`tests/unit/contract-parity.test.ts`.

---

## 4. Job lifecycle

```text
submit ──► queued ──► running ──► succeeded
              │          │
              │          ├──► failed      (error recorded, no partial commit)
              │          │
              └──────────┴──► cancelled   (timeout or client request)

Every transition appends an audit record. Terminal states are immutable.
```

---

## 5. Security controls (Phase 11)

1. **Deny by default**: unknown operation, missing root, expired token,
   or unmapped path ⇒ rejected.
2. **Path canonicalisation**: resolve symlinks and `..` before the prefix
   check; reject any path that escapes its root after resolution.
3. **No arbitrary process spawn**: operations map to reviewed functions.
4. **Least data**: the agent receives only the parameters it needs, never the
   whole environment.
5. **Limits**: max concurrent jobs (default 1), job timeout (default 3600 s),
   output size caps.
6. **Fail closed**: if auditing fails, the job does not start.
7. **Explicit start**: the agent is off by default
   (`LOCAL_AGENT_ENABLED=false`).

Full detail: [local agent security](../security/local-agent-security.md).

---

## 6. Failure handling

| Failure                 | Behaviour                                              |
| ----------------------- | ------------------------------------------------------ |
| Invalid/expired token   | 401, audit entry, no job created                        |
| Unknown operation       | 400, audit entry                                        |
| Path outside allow-list | 403, audit entry, job marked failed                     |
| Timeout                 | Job cancelled, partial output discarded                 |
| Crash                   | On restart, `running` jobs are marked failed with reason |
| Disk full / IO error    | Job failed with a typed error; no corrupt artefacts     |

---

## 7. Current state and exit criteria

**Phase 0:** contract implemented (`LocalAgentJob`, `JobOperation`,
`JobStatus`), mirrored in TypeScript, covered by tests. No server, no socket,
no execution.

**Phase 11 exit criteria:**

- Agent authenticates the API and rejects everything else.
- Operation and path allow-lists enforced with adversarial tests
  (`..`, symlinks, absolute-path tricks, case tricks on Windows).
- Timeouts, concurrency and cancellation work.
- Every job audited; audit is append-only.
- Security agent review recorded in `docs/security/local-agent-security.md`.
