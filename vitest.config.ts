import { defineConfig } from 'vitest/config';

export default defineConfig({
  // `apps/web/tsconfig.json` must say `jsx: preserve` for Next.js, but the
  // test runner has to transform JSX itself. Compile it with the automatic
  // React runtime instead of carrying the JSX through untouched.
  oxc: {
    jsx: { runtime: 'automatic' },
  },
  test: {
    include: [
      'tests/**/*.test.{ts,tsx}',
      'packages/*/src/**/*.test.{ts,tsx}',
      'apps/web/src/**/*.test.{ts,tsx}',
    ],
    exclude: ['node_modules/**', 'dist/**', 'coverage/**', '.next/**'],
    environment: 'node',
    reporters: ['default'],
    passWithNoTests: false,
    coverage: {
      provider: 'v8',
      include: ['packages/*/src/**/*.ts', 'apps/web/src/**/*.ts', 'apps/web/src/**/*.tsx'],
      reportsDirectory: 'coverage',
    },
  },
});
