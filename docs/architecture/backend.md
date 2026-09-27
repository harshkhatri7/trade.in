# Backend architecture

**Phase:** 1 — Application skeleton. `apps/api` **exists and runs**: a FastAPI
application with health and readiness endpoints, built on the shared
`src/harsh_quant_os` foundation (settings, safety gates, contracts).

---

## 1. Stack

| Choice                         | Reason                                                              |
| ------------------------------ | ------------------------------------------------------------------- |
| Python 3.12                    | Modern typing, matches the quant and local-agent stacks             |
| FastAPI                        | Async, typed request/response models, OpenAPI schema for free        |
| Pydantic v2                    | Runtime validation at every boundary                                 |
| pydantic-settings              | Typed, single-source environment configuration                       |
| Uvicorn                        | ASGI server suitable for FastAPI                                     |
| PostgreSQL + SQLAlchemy + Alembic (Phase 2) | Relational integrity, reviewable migrations           |

Already installed and configured in `.venv`: `fastapi`, `uvicorn`, `pydantic`,
`pydantic-settings`, `httpx2` (the HTTP test client required by Starlette's
TestClient), `pytest`, `ruff`, `mypy`.

---

## 2. Layering

```text
apps/api (HTTP concerns only)
  ├── routers        : parse, validate, map to service calls
  ├── middleware     : auth, request id, logging, error mapping
  └── dependencies   : construct services with an explicit Settings object
        │
        ▼
application services (orchestration, transactions, audit records)
        │
        ▼
domain (pure models and rules — no I/O, no framework imports)
        │
        ├── quant / risk / backtesting libraries
        └── repositories → storage layer
```

Rules:

1. Routers contain **no** business logic.
2. Domain code imports **nothing** from FastAPI or SQLAlchemy.
3. Services receive collaborators explicitly — no module-level singletons,
   no hidden global state.
4. Every write path that affects money, risk or history writes an audit
   record in the same transaction.

---

## 3. Configuration

All environment access is funnelled through
`harsh_quant_os.config.Settings`:

```python
from harsh_quant_os.config import Settings, SettingsError

try:
    settings = Settings.load()  # reads .env and the environment
except SettingsError as exc:
    raise SystemExit(f"configuration error: {exc}")
```

Guarantees already enforced by tests:

- `LIVE_TRADING_ENABLED=true` cannot be loaded;
- placeholder secrets are rejected outside `development`/`test`;
- unknown environment keys are ignored rather than silently accepted;
- `Settings.missing_secrets()` reports unset credentials.

See [secrets management](../security/secrets-management.md).

---

## 4. API conventions

| Concern            | Convention                                                        |
| ------------------ | ----------------------------------------------------------------- |
| Base URL           | `/api/v1/...`; `/health` and `/ready` are aliases of `/api/v1/health` and `/api/v1/ready` |
| Errors             | RFC 7807 problem+json: `type`, `title`, `status`, `detail`        |
| Validation         | 422 with field-level messages; never leak internals               |
| Auth               | Session cookie (web) + short-lived bearer (machine clients) — **not implemented; moved to Phase 2 by [ADR-0003](../decisions/ADR-0003-authentication-deferred.md)** |
| Idempotency        | `Idempotency-Key` header on any write that can move a position    |
| Pagination         | Cursor-based; explicit `has_more`                                 |
| Time               | ISO-8601 with timezone, always UTC in storage                     |
| Versioning         | Additive changes in place; breaking changes require a new prefix  |

Versioning and the shared-contract strategy are recorded in
[ADR-0002](../decisions/ADR-0002-shared-contract-without-codegen.md).

---

## 5. Error handling and logging

- Typed exception hierarchy; routers map to HTTP responses in one place.
- Structured JSON logs with a request id; secrets and payloads are never
  logged.
- Unhandled exceptions are logged with a stack trace and returned as a
  generic 500 — no internal detail crosses the boundary.
- `LOG_LEVEL` is configuration, not code.

---

## 6. Security posture

- Deny-by-default authorisation on every route — **not yet enforced**,
  because no authenticated surface exists; the gap and its mitigations are
  recorded in [ADR-0003](../decisions/ADR-0003-authentication-deferred.md).
- Rate limiting and CSRF protection arrive with authentication (Phase 2).
- Passwords hashed with Argon2id or bcrypt (Phase 2); never reversible.
- The API binds to `127.0.0.1` by default and CORS is an explicit
  allow-list from `API_ALLOWED_ORIGINS`; `Settings` rejects `*` outside
  `development`/`test`.
- No broker credentials exist anywhere in the API. If a future phase needs
  them, they live in a dedicated store with restricted access — see
  [broker security](../security/broker-security.md).
- The API is the **only** component allowed to talk to the local agent, and
  only through the authenticated job interface.

---

## 7. Testing

| Layer           | Tool     | Expectation                                        |
| --------------- | -------- | -------------------------------------------------- |
| Unit            | pytest   | Domain and service logic, fully deterministic       |
| API             | pytest + Starlette TestClient (`httpx2`) | Request/response, error mapping, CORS, config |
| Contract        | pytest   | Pydantic models match the TypeScript contract (both directions) |
| Integration     | pytest   | A real uvicorn process over real HTTP (`tests/integration/test_api_http.py`) |
| Security        | pytest   | Auth, authorisation, gate invariants               |

`pytest` is configured in `pyproject.toml` with `--strict-markers` and
`filterwarnings = ["error"]`.

---

## 8. Phase 1 exit criteria — as delivered

Delivered:

- FastAPI application with `GET /api/v1/health` and `GET /api/v1/ready`
  (aliases at `/health` and `/ready`), served from typed Pydantic models.
- Structured logging, request ids, problem+json error mapping, CORS from
  configuration.
- OpenAPI schema exposed outside production; the web client is **hand-typed
  against a shared fixture** rather than generated — see
  [ADR-0002](../decisions/ADR-0002-shared-contract-without-codegen.md).
- API, contract and integration tests green in CI.

Not delivered (recorded, not hidden):

- **Authentication with session management** — moved to Phase 2 by
  [ADR-0003](../decisions/ADR-0003-authentication-deferred.md); the roadmap
  was amended in the same change.
- Rate limiting and CSRF, which depend on authentication.
- `/ready` reports `database: not_configured`: there is no database in
  Phase 1 and the API does not claim otherwise.
