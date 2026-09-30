# `apps/api` — FastAPI service

**Phase 2 identity, plus the Phase 4 read surface (in progress).** The
read-only system endpoints, the session endpoints, and a read-only view of
the market data that has been ingested: no orders, no AI, no shell
execution, and no write path into `data/`. Sessions live in PostgreSQL
through `harsh_quant_os.auth`; nothing is cached in process memory, so a
restart does not lose them.

---

## What it serves

| Method | Canonical path           | Alias        | Purpose                                     |
| ------ | ------------------------ | ------------ | ------------------------------------------- |
| `GET`  | `/api/v1/health`         | `/health`    | Process is up: status, service, version, environment |
| `GET`  | `/api/v1/ready`          | `/ready`     | Readiness with explicit named checks        |
| `GET`  | `/api/v1/openapi.json`   | —            | Schema (non-production environments only)   |
| `POST` | `/api/v1/auth/login`     | —            | Open a session; sets the `hqos_session` cookie |
| `POST` | `/api/v1/auth/logout`    | —            | Revoke the current session (`204`)          |
| `GET`  | `/api/v1/me`             | —            | The authenticated account and its session   |
| `GET`  | `/api/v1/datasets`       | —            | Every dataset: provenance, quality status, version |
| `GET`  | `/api/v1/datasets/{name}` | —           | One dataset and its append-only acquisition history |
| `GET`  | `/api/v1/datasets/{name}/bars` | —      | One page of stored bars, tagged with its dataset version |

The system paths are one router mounted twice, so the alias can never drift
from the canonical route. The auth and dataset routes are deliberately
**not** aliased: there is exactly one spelling of each, under `/api/v1`.
Versioning is documented in [`hqos_api/routers/system.py`](hqos_api/routers/system.py)
and in [ADR-0002](../../docs/decisions/ADR-0002-shared-contract-without-codegen.md).

The dataset routes are **read-only and unauthenticated**, which is a
decision under `docs/architecture/backend.md` §6 rather than an oversight:
authentication covers what exposes or acts on an account, a session, a
strategy, a position or an order, and public market data plus its
provenance is none of those. They stay behind the loopback bind and the
CORS allow-list, they only ever `SELECT`, and every bars response carries
the `version` of the artefact it was read from. Refusals are explicit: a
timestamp with no UTC offset and an inverted window are `422`, an unknown
name is `404`, and a manifest row whose file is gone from `data/` is `409`
— never a short series pretending to be the whole one.

`/ready` performs a real round trip to PostgreSQL and reports `database: ok`
or `database: failed`; a failed check answers `503`. It is never reported as
healthy because a connection *should* work, and `not_configured` is no longer
produced — the application has a database now, so claiming otherwise would be
false.

### Example

```powershell
.\.venv\Scripts\python.exe -m uvicorn --app-dir apps\api main:app --host 127.0.0.1 --port 8000
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

```json
{
  "status": "ok",
  "service": "harsh-quant-os-api",
  "version": "0.1.0-alpha",
  "environment": "development"
}
```

---

## Layout

```text
apps/api/
├── main.py                 # module-level `app` + CLI entry point
└── hqos_api/
    ├── factory.py          # create_app(): lifespan, CORS, handlers, routers
    ├── cookies.py          # the one definition of the session cookie
    ├── dependencies.py     # auth context (401 when absent), session factory, store root
    ├── core/
    │   ├── errors.py       # RFC 7807 problem+json handlers
    │   ├── logging.py      # structured logging from Settings
    │   └── middleware.py   # request id + access logging
    ├── routers/
    │   ├── system.py       # health and readiness
    │   ├── auth.py         # login, logout, me
    │   └── datasets.py     # dataset directory, detail, bars (read-only)
    └── services/
        ├── system.py       # builds contract responses
        └── datasets.py     # manifest rows and stored artefacts, read-only
```

Rules this layout keeps:

1. Routers contain no business logic; they call services.
2. Services receive everything they need explicitly — a `Settings` object, a
   session factory, a store root — no global singleton, no
   dependency-injection container.
3. Responses are Pydantic models from `harsh_quant_os.contracts`, never
   untyped dictionaries.
4. Nothing in this app imports a broker SDK or executes shell commands.
   Database access happens only through `harsh_quant_os.db`,
   `harsh_quant_os.auth` and `harsh_quant_os.data.manifest`, never as ad hoc
   SQL inside a router.
5. The cookie's name, flags and lifetime are defined once, in `cookies.py`,
   so the response that sets it and the dependency that reads it cannot
   disagree.

---

## Configuration

All environment access goes through the shared
`harsh_quant_os.config.Settings` — this app defines no configuration of its
own. Relevant keys (see [`.env.example`](../../.env.example)):

| Key                    | Effect                                                |
| ---------------------- | ----------------------------------------------------- |
| `API_HOST`, `API_PORT` | Bind address (`127.0.0.1` by default)                 |
| `APP_ENV`              | Environment reported by `/health`; disables schema docs in `production` |
| `LOG_LEVEL`            | Log verbosity                                          |
| `API_ALLOWED_ORIGINS`  | CORS allow-list; `*` is rejected outside development/test |
| `DATABASE_URL`         | Where sessions and users are stored                    |
| `AUTH_SECRET_KEY`      | HMAC key that session tokens are stored under          |
| `AUTH_TOKEN_EXPIRY_MINUTES` | Session lifetime (default 60)                     |

`Settings.load()` reads `.env` from the working directory, so start the API
from the repository root (which `npm run api` and `start-dev.ps1` do).

---

## Error handling

Unhandled exceptions and request failures are returned as
`application/problem+json` with `type`, `title`, `status`, `detail` and the
`X-Request-ID` header. Internal detail never crosses the boundary: a database
that is down is a `503` with no connection string, no password and no
traceback in the body.

---

## Tests

| Suite                    | What it proves                                              |
| ------------------------ | ----------------------------------------------------------- |
| `tests/api/`             | Schema, status codes, versioning, CORS, config, error shape |
| `tests/api/test_auth_endpoints.py` | Login/logout/me status codes, indistinguishable refusals, no token in any body |
| `tests/api/test_contract_parity.py` | The TypeScript contract matches these Pydantic models |
| `tests/api/test_datasets_endpoints.py` | Dataset routes exist only under `/api/v1`, serve `GET` only, judge request shape before the database, and an unreachable database never answers an empty directory |
| `tests/api/test_datasets_contract_parity.py` | The dataset contracts match their TypeScript mirrors, in both directions, against one shared fixture |
| `tests/integration/test_api_http.py` | A real uvicorn process answers over real HTTP, and an unreachable database is a `503` |
| `tests/integration/test_auth_http.py` | The cookie round trip, revocation, and a session that survives an API restart |
| `tests/integration/test_datasets_http.py` | A real store and manifest row served by a real uvicorn process: provenance, exact digits, cursor paging, and each refusal with its status |

Run them with `npm run test:py` or `.\.venv\Scripts\python.exe -m pytest`.

---

## Not implemented

Orders, strategies, backtests, AI, paper trading, live trading. Market data
is readable but not *terminal*: the dataset endpoints above are the whole
API side of Phase 4 — the `/datasets` web page, its stored-bars chart,
watchlist and multi-timeframe panels consume them (the watchlist itself
lives in the browser, not in the API). There is no open registration
either:
accounts are created out of band with `hqos user create`. Live trading is
disabled by configuration and cannot be enabled here.
