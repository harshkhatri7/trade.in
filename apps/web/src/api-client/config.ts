/**
 * Where the browser finds the API.
 *
 * `NEXT_PUBLIC_*` values are inlined by Next.js at build time, so they are
 * public by definition and must never hold a secret. The default matches
 * `API_BASE_URL` in the repository's `.env.example`.
 *
 * Configure it in `apps/web/.env.local` (git-ignored):
 *
 *     NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
 */

/** Fallback used when no environment override is present. */
export const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000';

function normalise(baseUrl: string): string {
  return baseUrl.trim().replace(/\/+$/, '');
}

/** Resolve the API base URL for this build. */
export function resolveApiBaseUrl(): string {
  // The member access is written literally so the bundler can inline it.
  const configured =
    typeof process === 'undefined' ? undefined : process.env.NEXT_PUBLIC_API_BASE_URL;
  if (typeof configured === 'string' && configured.trim() !== '') {
    return normalise(configured);
  }
  return DEFAULT_API_BASE_URL;
}
