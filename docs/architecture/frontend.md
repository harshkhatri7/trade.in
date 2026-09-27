# Frontend architecture

**Phase:** 0 — Foundation. **`apps/web` is not implemented yet (Phase 1).**
This document fixes the decisions so Phase 1 has an agreed target.

---

## 1. Stack

| Choice                             | Reason                                                              |
| ---------------------------------- | ------------------------------------------------------------------- |
| Next.js (App Router)               | Server rendering where it helps, strong routing and build tooling   |
| TypeScript, `strict: true`         | Financial UI code must not rely on implicit `any`                   |
| Tailwind CSS                       | Fast, consistent styling without a heavy runtime                    |
| Accessible component architecture (shadcn/ui-style) | Composable, ownable components; no black-box vendor lock |
| TradingView Lightweight Charts     | Purpose-built for financial series, permissive licence, good performance |

Root configuration already in place: `tsconfig.json`, `eslint.config.mjs`,
`.prettierrc`. The web app will extend the root tsconfig rather than
duplicating compiler options.

---

## 2. Layering inside `apps/web`

```text
app/ (routes, layouts, pages)
  └── components/ (presentational, accessible)
        └── features/ (feature composition, data hooks)
              └── api-client/ (typed, generated from the API schema)
                    └── @harsh-quant-os/types + @harsh-quant-os/shared
```

Rules:

1. **No business logic in components.** Components render state and emit
   events.
2. **No direct data fetching outside `api-client`.** One typed client, one
   place to handle auth, errors and retries.
3. **No environment secrets in the browser bundle.** Next.js public env vars
   are non-secret by definition; anything secret belongs server-side.
4. **No filesystem, shell or broker access.** The browser talks to the API and
   nothing else.
5. **Types come from `@harsh-quant-os/types`**, which mirrors the Python
   contracts. Drift fails `tests/unit/contract-parity.test.ts`.

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
| Components        | Vitest    | Rendering, state transitions, accessibility rules |
| Contracts         | Vitest    | Type parity with Python, shape validation        |
| End-to-end        | Playwright| Login, navigation, research workflows (Phase 4+) |

Vitest is already configured at the repository root
(`vitest.config.ts`, `npm run test`).

---

## 6. Phase 1 exit criteria

- App shell with routing, layout and accessible primitives.
- Typed API client generated from the FastAPI schema.
- Authenticated read-only pages that render real API responses.
- No mocked "demo" data anywhere in the UI.
- `npm run lint`, `npm run typecheck`, `npm run test` all green.
