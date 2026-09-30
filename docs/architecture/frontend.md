# Frontend architecture

**Phase:** 4 — Market terminal (in progress). **`apps/web`** began as the
Phase 1 shell — layout, design tokens, the typed API client and the
system-status panel — and Phase 4 added the `/datasets` route. The
decisions below are the ones that produced both.

---

## 1. Stack

| Choice                             | Reason                                                              |
| ---------------------------------- | ------------------------------------------------------------------- |
| Next.js 16 (App Router)            | Server rendering where it helps, strong routing and build tooling   |
| React 19                           | Current rendering model, strict typing with TypeScript              |
| TypeScript, `strict: true`         | Financial UI code must not rely on implicit `any`                   |
| Tailwind CSS 4 (CSS-first `@theme`)| Fast, consistent styling without a heavy runtime; design tokens live in `globals.css` |
| Accessible component architecture (shadcn/ui-style) | Composable, ownable components; no black-box vendor lock |
| TradingView Lightweight Charts     | Purpose-built for financial series, permissive licence, good performance (Phase 4) |

Root configuration already in place: `tsconfig.json`, `eslint.config.mjs`,
`.prettierrc`. `apps/web/tsconfig.json` extends the root config and adds only
the DOM lib and the JSX settings Next.js requires — there is one set of
compiler options for the repository.

---

## 2. Layering inside `apps/web`

```text
src/app/            routes, layouts, pages
src/components/     presentational, accessible
src/features/       feature composition and data hooks
src/api-client/     the only place this app performs HTTP
      └── @harsh-quant-os/types + @harsh-quant-os/shared
```

Rules:

1. **No business logic in components.** Components render state and emit
   events.
2. **No direct data fetching outside `api-client`.** One typed client, one
   place to handle errors; components receive the client as a prop, which is
   how tests inject a fake.
3. **Request state is a closed union:** `loading` | `connected` | `error` |
   `unavailable`. There is no branch that assumes health.
4. **No environment secrets in the browser bundle.** Next.js public env vars
   are non-secret by definition; anything secret belongs server-side.
5. **No filesystem, shell or broker access.** The browser talks to the API and
   nothing else.
6. **Types come from `@harsh-quant-os/types`**, which mirrors the Python
   contracts; drift fails `tests/unit/health-contract.test.ts` and
   `tests/api/test_contract_parity.py` (see
   [ADR-0002](../decisions/ADR-0002-shared-contract-without-codegen.md)).

---

## 3. What the UI may show

Every research figure on screen must be traceable: dataset version, timeframe,
quality status, and the experiment or backtest that produced it. The UI never
displays a number that cannot be traced back to stored provenance.

Statuses the UI must distinguish honestly:

- `valid` / `suspect` / `invalid` / `pending` / `unknown` datasets;
- backtest vs. out-of-sample vs. paper vs. live (live never appears before
  Phase 16);
- estimated vs. actual fills.

---

## 4. Accessibility

- Semantic HTML, keyboard navigation, visible focus.
- Colour is never the only signal (P&L also uses text/sign).
- Charts expose a textual or table alternative.
- Contrast meets WCAG AA.
- Motion respects `prefers-reduced-motion`.

---

## 5. Testing

| Layer             | Tool      | Expectation                                    |
| ----------------- | --------- | ----------------------------------------------- |
| Components        | Vitest + jsdom + Testing Library | Rendering, state transitions, no false connection state |
| API client        | Vitest    | Path, validation, and network/http/contract errors kept distinct |
| Contracts         | Vitest + pytest | Type parity with Python, shape validation; see [ADR-0002](../decisions/ADR-0002-shared-contract-without-codegen.md) |
| Integration       | Vitest (jsdom) + real HTTP | A real API process → typed client → rendered DOM (`tests/integration/api-web-flow.test.tsx`) |
| End-to-end browser| Playwright| Login, navigation, research workflows (Phase 4+) — **not installed yet** |

Playwright is deliberately not added in Phase 1: it was not already present,
and the integration chain can be proved with a real HTTP round trip plus a
DOM render. The browser layer is adopted when a browser-only behaviour
actually needs it (Phase 4).

Vitest is configured at the repository root
(`vitest.config.ts`, `npm run test`). Component tests are jsdom-based via a
`@vitest-environment jsdom` docblock; everything else runs in Node.

---

## 6. Phase 1 exit criteria

Delivered:

- App shell with layout, accessible landmarks, skip link and design tokens.
- Typed API client with explicit `loading` / `connected` / `error` /
  `unavailable` states; network failures are never hidden.
- One read-only page that renders a real API response — no mocked data, no
  invented status, no fake charts or figures.
- Component, client, contract and integration tests green in CI.
- `npm run lint`, `npm run typecheck` (root **and** `apps/web`),
  `npm run test` and `npm run build:web` all green.

Not delivered (recorded, not hidden):

- **Authentication and session management** moved to Phase 2 by
  [ADR-0003](../decisions/ADR-0003-authentication-deferred.md), which restates
  the roadmap exit criteria for this phase.
- Routing beyond the single shell page, and generated client code — both
  deferred with the same ADR trail as above. Routing arrived in Phase 4
  with `/datasets` (§7); generated client code is still not used.

---

## 7. Phase 4 — the dataset browser

`/datasets` is the first route after the shell page, and it is split the
same way as everything else:

- `app/datasets/page.tsx` — server component: page metadata and copy only;
- `components/dataset-browser.tsx` — renders the directory and, once a
  dataset is selected, its provenance panel; owns the page's single
  `useWatchlist()` call, so the directory's Follow toggles and the
  watchlist panel below it always read and write one state;
- `components/dataset-watchlist.tsx` — the "Watchlist" panel: followed
  datasets with their stored metadata, names the directory no longer
  carries marked "(not in directory)" and still removable, and the
  directory's request state rendered with §2's shared wording;
- `components/dataset-multi-timeframe.tsx` — the "Multi-timeframe views"
  panel: every canonical timeframe chip per instrument, a button exactly
  where a stored dataset matches (it opens that dataset by name), a
  dashed non-interactive chip everywhere else, and a footnote naming any
  dataset the grid cannot place;
- `features/datasets/use-watchlist.ts` — `useWatchlist()`, the one
  localStorage-backed list behind both the Follow toggles and the
  watchlist panel: corrupt or non-array storage reads as an empty list,
  hydration happens after mount so SSR renders nothing invented, and a
  toggle before hydration cannot wipe a stored list;
- `components/dataset-bars.tsx` — the "Stored bars" section inside that
  panel: a candlestick chart of the requested window plus a table of the
  same payload;
- `features/datasets/use-datasets.ts` — `useDatasetList()` once on mount,
  and `useDatasetDetail()`/`useDatasetBars()` over one shared
  name-keyed helper, each a closed union of §2 rule 3 plus `idle`:
  nothing is fetched until the operator selects a dataset, and "not
  started" is a different fact from "failed";
- `features/common/api-failure.ts` — the shared classification of network,
  HTTP and contract failures, used by the system panel and the dataset
  panel alike so the two cannot drift apart;
- `features/common/request-state.ts` — the one place the request states
  get their wording and colour (`LOADING`, `CONNECTED`, `ERROR`,
  `DISCONNECTED`), so the system panel and the dataset panels cannot read
  differently for the same state.

Traceability rules the page enforces (§3):

- the directory shortens the artefact version to fit the table; the detail
  panel always shows the full SHA-256, so a figure can name its artefact
  exactly;
- the directory shows the acquisition timestamp to whole seconds so the
  table fits the viewport; the exact recorded value is carried on the
  cell's `title` and rendered in full in the detail panel;
- acquisition checksums are shown in full — a shortened checksum cannot be
  verified against anything;
- a `null` field renders as `—`, never `0`: "not recorded" and "zero rows"
  are different facts;
- quality status is a word plus a colour, never colour alone;
- failure messages reach the screen unchanged: an unreachable API, an HTTP
  status and a contract violation remain three distinguishable states.

The chart itself (`lightweight-charts`, reason recorded in §1) draws one
explicit window — `BARS_LIMIT = 200` rows per request — and the panel says
out loud when the API reports more rows than the window holds, so a page of
the series is never presented as the series. Chart and table read the same
payload: prices are decimal strings that become numbers only for the
chart's geometry, while the table prints the stored strings verbatim
(`78563.0`, never a rounded `78563`). The full artefact version from that
payload sits directly above the figure, and a bar timestamp that does not
parse can never reach the chart — `parseBarPoint` in the shared contract
rejects it first, and the panel renders `error` instead of a chart.

Accessibility of the section was verified with axe-core on the open panel:
the chart container is a labelled `role="figure"`, not `role="img"`,
because the charting library renders its TradingView attribution link
inside and `img` is a leaf role; the scrollable table wrapper is a named,
focusable region (`tabindex="0"`) so keyboard-only operators can read the
rows below the fold. Because jsdom has no canvas, component tests stub
`lightweight-charts` and assert the data handed to it; the rendered pixels
are verified in a real browser.

Rules the watchlist and multi-timeframe panels add:

- a timeframe chip is interactive only where a stored dataset exists; the
  rest are dashed spans marked "(not stored)" for screen readers — the
  grid may show absence but never offer a link to nothing;
- a dataset the grid cannot place (no instrument and/or timeframe) is
  named in the footnote, never silently dropped;
- the two panels render the directory's request state with §2's shared
  vocabulary, so neither can read CONNECTED while the directory has not
  answered;
- the "not stored" chips carry the muted token at full opacity: an
  `opacity-60` dimming was removed after axe-core measured 3.48:1 against
  the raised surface (4.5:1 is required at 12 px);
- the whole `/datasets` page — directory, both panels, open detail — was
  rescanned with axe-core after increment 4: 0 violations, 44 checks
  passed, and Lighthouse scored accessibility, best-practices and SEO
  1.0 each with zero failures.
