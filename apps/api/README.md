# apps/api — API service (Phase 1)

FastAPI entrypoint for HARSH QUANT OS.

**Status: not implemented.** Phase 0 provides the shared foundation package
that this service will import.

Planned layout:

```text
apps/api/
├── main.py               # ASGI app factory, middleware, router registration
├── routers/              # HTTP only: parse, validate, delegate
├── dependencies/         # Settings, auth context, service wiring
└── tests/                # API-level tests (also see /tests/integration)
```

What already exists for it:

| Piece                          | Location                                       |
| ------------------------------ | ---------------------------------------------- |
| Typed configuration            | `src/harsh_quant_os/config`                    |
| Trade gate / safety gates      | `src/harsh_quant_os/safety`                    |
| Data + job contracts           | `src/harsh_quant_os/contracts`                 |
| Memory categories              | `src/harsh_quant_os/memory`                    |
| Runtime dependencies installed | FastAPI, Uvicorn, Pydantic, httpx (in `.venv`) |

Ground rules: deny-by-default authorisation, audit records for state changes,
RFC 7807 errors, no broker endpoints, live trading unreachable.

See [docs/architecture/backend.md](../../docs/architecture/backend.md).
