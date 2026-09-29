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
| PostgreSQL + SQLAlchemy + Alembic (Phase 2, delivered) | Relational integrity, reviewable migrations           |

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
| Auth               | Session cookie `hqos_session` (HttpOnly, SameSite=Lax) opened by `POST /api/v1/auth/login` and consumed by `GET /api/v1/me` and `POST /api/v1/auth/logout` — delivered in Phase 2 per [ADR-0003](../decisions/ADR-0003-authentication-deferred.md). No bearer tokens for machine clients yet |
| Idempotency        | `Idempotency-Key` header on any write that can move a position    |
| Pagination         | Cursor-based; explicit `has_more`                                 |
| Time               | ISO-8601 with timezone, always UTC in storage                     |
| Versioning         | Additive changes in place; breaking changes require a new prefix  |

Versioning and the shared-contract strategy are recorded in
[ADR-0002](../decisions/ADR-0002-shared-contract-without-codegen.md).

**Dataset reads (Phase 4, in progress)** — `GET /api/v1/datasets`,
`GET /api/v1/datasets/{name}` and `GET /api/v1/datasets/{name}/bars`:

- Read-only, `GET` only, versioned only — no unversioned alias, because a
  load balancer has no business listing research data.
- Unauthenticated under section 6: they expose public market data and the
  record of where it came from, not an account, a session, a strategy, a
  position or an order. The loopback bind and the CORS allow-list are what
  keep them local; publishing research data beyond loopback would make
  authentication the first change, not the last.
- Cursor pagination in the convention above: `limit`, `start`/`end` bounds
  and `cursor`, with `has_more` and `next_cursor`.
- A timestamp without a UTC offset is refused (`422`), and so is an
  inverted window — otherwise a caller's mistake and a genuinely empty
  range would both answer `returned: 0` and the response could no longer
  tell them apart.
- Unknown name is `404`. A manifest row that exists but cannot be read —
  no artefact, no timeframe, a path that leaves the store, or a file gone
  from `data/` — is `409`, never a shorter series than the manifest
  claims.
- Every bars response carries the dataset `version` it was read from, so a
  figure drawn from it can name its artefact.

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

- Authentication is required for everything that exposes or acts on an
  account: `GET /api/v1/me` and `POST /api/v1/auth/logout` answer `401`
  without a valid session, and there is no anonymous write path.
  `/health` and `/ready` stay unauthenticated on purpose — a probe that
  needs a credential cannot tell you whether the process is alive. The
  dataset read endpoints stay unauthenticated by the same rule: they are
  `GET`-only reads of public market data and its provenance, they name no
  account, and section 4 records what changes if that data is ever
  published beyond loopback.
- **Rate limiting and a per-request CSRF token are not implemented.**
  Authentication landed in Phase 2; these two did not. What is in force is
  `SameSite=Lax` on the session cookie, a `127.0.0.1` bind by default and an
  explicit CORS allow-list. This is a recorded gap, not a claim of
  protection — see [ADR-0003](../decisions/ADR-0003-authentication-deferred.md).
- Passwords hashed with Argon2id (`argon2-cffi`, m=45056 KiB, t=3, p=1);
  never reversible. A session token exists in plaintext only in the
  `Set-Cookie` header: storage keeps an HMAC-SHA256 digest.
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

Not delivered in Phase 1 (recorded, not hidden — all three are addressed in
section 9):

- **Authentication with session management** — moved to Phase 2 by
  [ADR-0003](../decisions/ADR-0003-authentication-deferred.md); the roadmap
  was amended in the same change.
- Rate limiting and CSRF, which depend on authentication.
- `/ready` reported `database: not_configured`, because Phase 1 had no
  database and the API did not claim health it could not observe.

---

## 9. Phase 2 — database and authentication, as delivered

- PostgreSQL through SQLAlchemy 2.0 (async) with Alembic migrations; two
  revisions (`930c38609bc3`, `3842df3d0db8`) build the schema from empty.
  `alembic/env.py` prefers `HQOS_DATABASE_URL` and otherwise reads `Settings`.
- Tables: `users`, `sessions`, `audit_log`, plus the research schema
  `datasets`, `dataset_provenance`, `strategies`, `experiments` and
  `journal_entries`. `audit_log` and `dataset_provenance` are append-only by
  trigger; `audit_log` additionally has a `CHECK` constraint on `event_type`.
- The research tables have **no writer**: nothing in the application inserts
  into them. They are a schema, not a feature.
- `AuthService`: Argon2id password hashing, session tokens stored as an
  HMAC-SHA256 digest, login/logout/me over HTTP with the `hqos_session`
  cookie.
- Unknown account and wrong password produce byte-identical refusals; both
  are audited, so the distinction lives in the log rather than on the wire.
- An unreachable database is a `503` with no `Set-Cookie`, no connection
  string and no traceback in the body.
- A session survives an API restart, which is what storing it in PostgreSQL
  rather than in process memory is for.
- Backup and restore (`harsh_quant_os.db.backup`): every table in one
  transaction, the Alembic revision recorded in the manifest, a restore
  refused at a different revision or into populated data unless asked, and
  sequences re-aimed so the next insert cannot collide. Verified end to end
  by `tests/integration/test_backup_restore.py`.

Rate limiting and a per-request CSRF token remain unimplemented. Neither
appears on ROADMAP.md's Phase 2 list; both are open gaps rather than
finished work, and neither should be described as done.
