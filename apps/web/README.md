# `apps/web` — Next.js front end

**Phase 1 — Application skeleton.** A dark, minimal, accessible shell whose
only data source is the API. There are no charts, no market numbers, no
P&L, no positions and no trading controls in this application.

---

## What it shows

- The phase the platform is in (**Foundation / Application skeleton**).
- **API connection state**, derived from a real request: `LOADING`,
  `CONNECTED`, `ERROR` or `DISCONNECTED`.
- The `version`, `environment` and endpoint returned by `GET /api/v1/health`.
- What Phase 1 implements, and — explicitly — what it does not.

`CONNECTED` is only rendered after a validated response arrives. If the API
is unreachable, or answers with something that does not match the shared
contract, the panel says so. No value on the page is hard-coded.

---

## Layout

```text
apps/web/
├── src/
│   ├── app/                # App Router: layout, page, design tokens
│   ├── api-client/         # the only place the app performs HTTP
│   │   ├── config.ts       # base URL from NEXT_PUBLIC_API_BASE_URL
│   │   └── client.ts       # typed client: network / http / contract errors
│   ├── features/system/    # useSystemStatus(): loading/connected/error/unavailable
│   └── components/         # SystemStatus panel
├── next.config.ts
├── tsconfig.json           # extends the repository root config
└── .env.example            # NEXT_PUBLIC_API_BASE_URL
```

Rules this layout keeps:

1. Components never call `fetch`; they take an `ApiClient` (the default is
   injected by the component itself, which lets tests inject a fake).
2. Request states are a closed union — there is no implicit "assume
   healthy" branch.
3. Every string that reaches the screen comes from a validated response or
   is a static label.

---

## Configuration

Copy [`.env.example`](.env.example) to `.env.local` to override the API URL
for one machine:

```text
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

`NEXT_PUBLIC_` values are compiled into the browser bundle: they are public
by definition and must never contain a secret. `npm run dev` sets this value
from `API_BASE_URL` in the repository root `.env`, so there is one source of
truth.

---

## Commands

```powershell
npm run web          # dev server (root script; reads ports from .env)
npm run build:web    # production build
npm run typecheck    # tsc for the root project and this app
```

The dev server binds to `WEB_HOST`/`WEB_PORT` (`127.0.0.1:3000` by default).

---

## Tests

| Suite                          | What it proves                                              |
| ------------------------------ | ----------------------------------------------------------- |
| `tests/web/api-client.test.ts` | Paths, validation and the three distinct failure kinds      |
| `tests/web/system-status.test.tsx` | Each state renders; no state claims a connection that did not happen |
| `tests/integration/api-web-flow.test.tsx` | Real API → real client → real DOM                 |

Run them with `npm run test`.

---

## Not implemented

Authentication (Phase 2, see [ADR-0003](../../docs/decisions/ADR-0003-authentication-deferred.md)),
routing beyond the shell page, market data, charts, strategies, backtests,
AI, paper trading, live trading.
