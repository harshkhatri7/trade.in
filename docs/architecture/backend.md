# Backend architecture

**Phase:** 0 — Foundation. `apps/api` is **not implemented yet (Phase 1)**.
The shared foundation it will build on — `src/harsh_quant_os` — exists and is
tested today.

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
`pydantic-settings`, `httpx` (test client), `pytest`, `ruff`, `mypy`.

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
| Base URL           | `/api/v1/...`                                                     |
| Errors             | RFC 7807 problem+json: `type`, `title`, `status`, `detail`        |
| Validation         | 422 with field-level messages; never leak internals               |
| Auth               | Session cookie (web) + short-lived bearer (machine clients)       |
| Idempotency        | `Idempotency-Key` header on any write that can move a position    |
| Pagination         | Cursor-based; explicit `has_more`                                 |
| Time               | ISO-8601 with timezone, always UTC in storage                     |
| Versioning         | Additive changes in place; breaking changes require a new prefix  |

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

- Deny-by-default authorisation on every route.
- Rate limiting and CSRF protection in Phase 1.
- Passwords hashed with Argon2id or bcrypt (Phase 1); never reversible.
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
| API             | pytest + httpx | Request/response, auth, error mapping         |
| Contract        | pytest   | OpenAPI schema matches the TypeScript client types |
| Security        | pytest   | Auth, authorisation, gate invariants               |

`pytest` is configured in `pyproject.toml` with `--strict-markers` and
`filterwarnings = ["error"]`.

---

## 8. Phase 1 exit criteria

- FastAPI app with health and version endpoints.
- Structured logging, request ids, consistent error mapping.
- Authentication with session management.
- OpenAPI schema consumed by the typed web client.
- API, auth and contract tests green in CI.
