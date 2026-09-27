import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts', 'packages/*/src/**/*.test.ts'],
    exclude: ['node_modules/**', 'dist/**', 'coverage/**'],
    environment: 'node',
    reporters: ['default'],
    passWithNoTests: false,
    coverage: {
      provider: 'v8',
      include: ['packages/*/src/**/*.ts'],
      reportsDirectory: 'coverage',
    },
  },
});
