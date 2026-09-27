# apps/web — Market terminal (Phase 1)

Next.js + TypeScript + Tailwind application.

**Status: not implemented.** Phase 0 created the repository, tooling and
documentation; the application shell arrives in Phase 1.

When Phase 1 starts, this directory will contain:

```text
apps/web/
├── package.json          # workspace: added to the root "workspaces" list
├── next.config.ts
├── src/app/              # routes and layouts
├── src/components/       # accessible presentational components
├── src/features/         # feature composition
└── src/api-client/       # typed client generated from the API schema
```

Rules that already apply:

- TypeScript `strict`; no `any` (ESLint error).
- No secrets in client code; the browser talks only to the API.
- No filesystem, shell or broker access from the browser.
- Every displayed figure must be traceable to a dataset version.

See [docs/architecture/frontend.md](../../docs/architecture/frontend.md).
