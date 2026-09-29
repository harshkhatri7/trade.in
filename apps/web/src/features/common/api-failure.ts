/**
 * The two failure states every request state in this application can enter.
 *
 * Classification lives in one place so no feature can quietly drift: an
 * unreachable API is `unavailable` (the request never completed — the process
 * is down, the address is wrong, or CORS refused), while an answer that
 * arrived but cannot be used — an HTTP status, or a payload that fails the
 * shared contract — is `error`. Neither is ever a success state.
 *
 * Mirrors the distinction documented in `docs/architecture/frontend.md` §2,
 * rule 3.
 */
import { ApiClientError } from '../../api-client';

export type ApiFailureState =
  | { readonly kind: 'unavailable'; readonly message: string }
  | { readonly kind: 'error'; readonly message: string };

/** Map a client failure onto the failure state the UI should render. */
export function classifyApiFailure(error: unknown): ApiFailureState {
  if (error instanceof ApiClientError && error.kind === 'network') {
    return { kind: 'unavailable', message: error.message };
  }
  if (error instanceof ApiClientError) {
    return { kind: 'error', message: error.message };
  }
  return { kind: 'error', message: 'Unexpected failure while contacting the API.' };
}
