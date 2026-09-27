# Frontend architecture

**Phase:** 1 — Application skeleton. **`apps/web` is implemented** as a shell:
layout, design tokens, the typed API client and the system-status panel. The
decisions below are the ones that produced it.

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
  deferred with the same ADR trail as above.
