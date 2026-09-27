import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    // Generated directories are ignored anywhere in the tree: patterns with a
    // leading `**/` are required because flat-config ignores are anchored to
    // the config file's directory (`apps/web/.next` is not `.next`).
    ignores: [
      '**/node_modules/**',
      '**/dist/**',
      '**/build/**',
      '**/coverage/**',
      '**/.next/**',
      '**/out/**',
      'data/**',
      '.venv/**',
      'venv/**',
      '**/site-packages/**',
      'research/notebooks/**',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.ts', '**/*.tsx', '**/*.mts'],
    languageOptions: {
      parserOptions: {
        projectService: false,
      },
    },
    rules: {
      // No `any`: type safety is a hard requirement for financial code.
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { prefer: 'type-imports', fixStyle: 'inline-type-imports' },
      ],
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      'no-console': ['error', { allow: ['warn', 'error'] }],
      'prefer-const': 'error',
      'no-var': 'error',
    },
  },
  {
    // Scripts and configuration files legitimately log to the console.
    files: ['scripts/**/*.ts', '**/*.config.ts', '**/*.mjs'],
    rules: {
      'no-console': 'off',
    },
  },
  prettier,
);
