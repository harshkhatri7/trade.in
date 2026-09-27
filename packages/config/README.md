# @harsh-quant-os/config

Placeholder for shared runtime configuration objects (feature flags, UI
constants, validated config presets) consumed by more than one TypeScript
package.

**Status: empty by design.**

Tooling configuration (TypeScript, ESLint, Prettier) deliberately lives at the
repository root — `tsconfig.json`, `eslint.config.mjs`, `.prettierrc` — so
there is exactly one copy of each rule. Do not duplicate them here.

This directory gains content only when a second consumer exists.
