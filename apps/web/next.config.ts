import type { NextConfig } from 'next';

/**
 * Next.js configuration for HARSH QUANT OS.
 *
 * Deliberately small. The interesting rules (strict TypeScript, ESLint,
 * formatting) live at the repository root so that every workspace is checked
 * the same way; `next build` only re-runs the TypeScript check.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,

  // Next.js can generate `AGENTS.md`/`CLAUDE.md` next to this app. The
  // repository already has one governing AGENTS.md (see section 9: it is the
  // highest-authority document), and every `*.md` in the tree is checked by
  // `tests/unit/test_documentation.py` for resolving links and blocked
  // claims. Unowned, version-churning files in that scope are a liability, so
  // the generation is switched off deliberately.
  agentRules: false,

  // ESLint and formatting are not run by Next.js: the repository runs them
  // once, from the root (`npm run lint`, `npm run format:check`), with the
  // shared flat config. `next build` still type-checks this app.

  // The shared packages ship TypeScript sources, so they are compiled with the
  // app instead of being pre-built.
  transpilePackages: ['@harsh-quant-os/types', '@harsh-quant-os/shared'],
};

export default nextConfig;
