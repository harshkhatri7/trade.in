# `apps/api` — FastAPI service

**Phase 1 — Application skeleton.** Read-only system endpoints. No database,
no market data, no orders, no AI, no shell execution.

---

## What it serves

| Method | Canonical path           | Alias        | Purpose                                     |
| ------ | ------------------------ | ------------ | ------------------------------------------- |
| `GET`  | `/api/v1/health`         | `/health`    | Process is up: status, service, version, environment |
| `GET`  | `/api/v1/ready`          | `/ready`     | Readiness with explicit named checks        |
| `GET`  | `/api/v1/openapi.json`   | —            | Schema (non-production environments only)   |

Both paths are one router mounted twice, so the alias can never drift from
the canonical route. Versioning is documented in
[`hqos_api/routers/system.py`](hqos_api/routers/system.py) and in
[ADR-0002](../../docs/decisions/ADR-0002-shared-contract-without-codegen.md).

`/ready` reports `database: not_configured`. Phase 1 has no database, and the
API states that instead of implying health it cannot observe.

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
    ├── core/
    │   ├── errors.py       # RFC 7807 problem+json handlers
    │   ├── logging.py      # structured logging from Settings
    │   └── middleware.py   # request id + access logging
    ├── routers/system.py   # health and readiness
    └── services/system.py  # builds contract responses
```

Rules this layout keeps:

1. Routers contain no business logic; they call services.
2. Services receive an explicit `Settings` object — no global singleton, no
   dependency-injection container.
3. Responses are Pydantic models from `harsh_quant_os.contracts.system`,
   never untyped dictionaries.
4. Nothing in this app imports a broker SDK, opens a database connection or
   executes shell commands.

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

`Settings.load()` reads `.env` from the working directory, so start the API
from the repository root (which `npm run api` and `start-dev.ps1` do).

---

## Error handling

Unhandled exceptions and request failures are returned as
`application/problem+json` with `type`, `title`, `status`, `detail` and the
`X-Request-ID` header. Internal detail never crosses the boundary.

---

## Tests

| Suite                    | What it proves                                              |
| ------------------------ | ----------------------------------------------------------- |
| `tests/api/`             | Schema, status codes, versioning, CORS, config, error shape |
| `tests/api/test_contract_parity.py` | The TypeScript contract matches these Pydantic models |
| `tests/integration/test_api_http.py` | A real uvicorn process answers over real HTTP         |

Run them with `npm run test:py` or `.\.venv\Scripts\python.exe -m pytest`.

---

## Not implemented

Authentication (Phase 2, see [ADR-0003](../../docs/decisions/ADR-0003-authentication-deferred.md)),
database access (Phase 2), market data, strategies, backtests, AI, paper
trading, live trading. Live trading is disabled by configuration and cannot
be enabled here.
