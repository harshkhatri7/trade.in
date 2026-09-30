# `apps/web` — Next.js front end

**Phase 1 shell, Phase 4 pages.** A dark, minimal, accessible application
whose only data source is the API. The home page renders connection state;
`/datasets` renders the ingested market data with its provenance and charts
the stored bars of the selected dataset. There is no P&L, no positions and
no trading controls in this application.

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
- **Stored bars**: a candlestick chart (TradingView Lightweight Charts) of
  one window of bars from `GET /api/v1/datasets/{name}/bars`, drawn in the
  dataset's own colours, above a table of the same payload printing every
  price verbatim. The full artefact version sits above the figure, and when
  the API reports more rows than the window holds the panel says so instead
  of implying the series is complete.
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
│   │   ├── common/         # request-failure classification, request-state labels
│   │   ├── system/         # useSystemStatus(): loading/connected/error/unavailable
│   │   └── datasets/       # useDatasetList()/useDatasetDetail()/useDatasetBars()
│   └── components/         # SystemStatus panel, DatasetBrowser, DatasetBars chart
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
   The chart and its table read one payload, so what is drawn and what is
   printed cannot disagree, and decimal prices become numbers only for the
   chart's geometry — the table keeps the stored strings.

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
| `tests/web/dataset-browser.test.tsx` | Each state renders from the shared fixture; nulls stay `—`, provenance loads on selection; Follow round-trips through the watchlist panel; the multi-timeframe panel offers only stored timeframes |
| `tests/web/dataset-bars.test.tsx` | The chart is stubbed (jsdom has no canvas): it receives converted numbers while the table keeps exact strings; every request state renders |
| `tests/web/dataset-watchlist.test.tsx` | The panel renders only what it was given: exact metadata, `—` for nulls, names that left the directory kept and removable, shared request-state wording |
| `tests/web/dataset-multi-timeframe.test.tsx` | Canonical timeframe order, buttons only where a dataset is stored, clicks open datasets by their real name, unplaceable datasets named |
| `tests/web/use-watchlist.test.ts` | Storage honesty: corrupt/non-array reads as empty, dedupe, order, persistence, quota failure keeps working |
| `tests/integration/api-web-flow.test.tsx` | Real API → real client → real DOM                 |

Run them with `npm run test`.

---

## Not implemented

Authentication UI (Phase 2, see [ADR-0003](../../docs/decisions/ADR-0003-authentication-deferred.md)),
strategies, backtests, AI,
paper trading, live trading. Market data is shown read-only on
`/datasets`; the chart there draws one requested window of stored bars —
it is not a live or streaming feed. The watchlist and multi-timeframe
panels are stored in this browser only — they do not sync anywhere.
