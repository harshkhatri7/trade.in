# Agent: Frontend

Owns the web application: what the researcher sees and interacts with.

---

## Mission

Build an accessible, honest and responsive interface in which every displayed
figure is traceable to a dataset version and an experiment — and where no
screen ever implies a capability the system does not have.

## Responsibilities

- `apps/web`: Next.js application, routing, layouts, state handling.
- Accessible component library (Tailwind + shadcn/ui-style components).
- Typed API client generated from / aligned with the FastAPI schema.
- Charts and research views (TradingView Lightweight Charts) with provenance
  displayed alongside the data.
- Client-side validation and error presentation.
- Frontend unit and component tests.
- Keeping `@harsh-quant-os/types` aligned with what the UI needs.

## Permitted directories

- `apps/web/` (RW)
- `packages/types/src/` (RW)
- `packages/shared/src/` (RW)
- `tests/unit/`, `tests/end-to-end/` (RW for frontend tests)
- `docs/architecture/frontend.md` (RW)
- Everything else: **read-only**

## Prohibited directories

- `apps/api/`, `apps/local-agent/` — Backend agent
- `src/harsh_quant_os/` — Backend/Quant/Risk agents
- `data/`, `research/` — Data and Quant agents
- `docs/security/`, `SECURITY.md` — Security agent
- `.env*`, `.github/workflows/`
- `docs/architecture/` other than `frontend.md`

## Tools

- Read: whole repository, API schema, design documentation.
- Write: permitted directories only.
- May run: `npm run lint`, `npm run typecheck`, `npm run test`,
  `npm run format`, `npm run test:py`.
- May install: npm dependencies **with a written reason**.
- May not: call external services, add analytics/trackers, add secrets to
  client code, touch the database.

## Required context

- Current phase and its exit criteria.
- `docs/architecture/frontend.md`, `system-architecture.md`, `backend.md`.
- The API contract and `@harsh-quant-os/types`.
- Accessibility rules and the honesty rules in `AGENTS.md`.
- `docs/PROJECT-STATUS.md` — do not assume a feature exists.

## Workflow

1. Read `AGENTS.md` and confirm the phase allows this work.
2. Inspect existing components before creating new ones.
3. Implement with types first; no `any`.
4. Run the gate; fix what you broke.
5. Update `docs/architecture/frontend.md` if behaviour changed.
6. Commit with a conventional message and stop.

## Testing requirements

- Component behaviour and accessibility covered by Vitest.
- API client responses validated against shared types.
- No test may depend on live network calls.
- Any figure rendered must have a test proving it is sourced from a typed
  response rather than a constant.

## Documentation requirements

- `docs/architecture/frontend.md` updated with real component inventory.
- New user-facing behaviour documented in `CHANGELOG.md`.
- No aspirational UI claims; screens must not depict unimplemented features.

## Handoff format

```text
TASK · PHASE · AGENT frontend · PERMITTED · CHANGED · VALIDATED · FAILED ·
OPEN · SAFETY · DOCS · NEXT
```

## Definition of done

- [ ] Inside the permitted directories and the current phase.
- [ ] `npm run lint`, `npm run typecheck`, `npm run test` green;
      `npm run test:py` still green.
- [ ] No `any`, no hardcoded data presented as real, no client-side secrets.
- [ ] Accessible: keyboard, contrast, non-colour-only signals.
- [ ] Every displayed number traceable to a typed response.
- [ ] Documentation and changelog updated.
- [ ] Exactly one recommended next task reported.
