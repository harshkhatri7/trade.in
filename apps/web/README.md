# `apps/web` — Next.js front end

**Phase 1 shell, Phase 4 pages.** A dark, minimal, accessible application
whose only data source is the API. The home page renders connection state;
`/datasets` renders the ingested market data with its provenance. There are
no charts, no P&L, no positions and no trading controls in this
application.

---

## What it shows

- The phase the platform is in (**market terminal, in progress**).
- **API connection state**, derived from a real request: `LOADING`,
  `CONNECTED`, `ERROR` or `DISCONNECTED`.
- The `version`, `environment` and endpoint returned by `GET /api/v1/health`.
- **`/datasets`**: every dataset with instrument, timeframe, quality
  status, row count, artefact version and acquisition time — and, for the
  selected dataset, the full SHA-256, storage path and the append-only
  acquisition history behind it.
- What exists so far, and — explicitly — what it does not.

`CONNECTED` is only rendered after a validated response arrives. If the API
is unreachable, or answers with something that does not match the shared
contract, the panel says so. No value on the page is hard-coded, and a
field the API never recorded shows as `—` — never as `0`.

---

## Layout

```text
apps/web/
├── src/
│   ├── app/                # App Router: layout, home page, design tokens
│   │   └── datasets/       # /datasets page (metadata + DatasetBrowser)
│   ├── api-client/         # the only place the app performs HTTP
│   │   ├── config.ts       # base URL from NEXT_PUBLIC_API_BASE_URL
│   │   └── client.ts       # typed client: health, readiness, dataset reads
│   ├── features/
│   │   ├── common/         # shared request-failure classification
│   │   ├── system/         # useSystemStatus(): loading/connected/error/unavailable
│   │   └── datasets/       # useDatasetList()/useDatasetDetail()
│   └── components/         # SystemStatus panel, DatasetBrowser
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
4. Every figure on `/datasets` sits next to the dataset version it was read
   from; a value that was never recorded is rendered as `—`, never as zero.

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
| `tests/web/dataset-browser.test.tsx` | Each state renders from the shared fixture; nulls stay `—`, provenance loads on selection |
| `tests/integration/api-web-flow.test.tsx` | Real API → real client → real DOM                 |

Run them with `npm run test`.

---

## Not implemented

Authentication UI (Phase 2, see [ADR-0003](../../docs/decisions/ADR-0003-authentication-deferred.md)),
charts, watchlists, multi-timeframe views, strategies, backtests, AI,
paper trading, live trading. Market data is shown read-only on
`/datasets`; no charting library has been added yet.
