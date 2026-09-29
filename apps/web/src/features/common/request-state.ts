/**
 * Presentation of the request states every panel in this app renders.
 *
 * The states themselves are declared per feature (health, directory,
 * provenance, bars) because each request is genuinely different; what must
 * not drift is how a state *reads* on screen. One module keeps that wording
 * and colouring in one place:
 *
 * - `LOADING` covers `idle` and `loading` alike: to the operator, "not
 *   started" and "in flight" are the same thing to wait for; the difference
 *   matters to the code, not to the screen.
 * - `DISCONNECTED` is only ever reached through the network failure
 *   classifier, so it never means "answered badly".
 * - Colour never carries meaning alone — the label is always rendered as
 *   text next to it, and the tone classes only tint that same text.
 */

export type RequestStateKind = 'idle' | 'loading' | 'connected' | 'error' | 'unavailable';

export const REQUEST_STATE_LABELS: Record<RequestStateKind, string> = {
  idle: 'LOADING',
  loading: 'LOADING',
  connected: 'CONNECTED',
  error: 'ERROR',
  unavailable: 'DISCONNECTED',
};

export const REQUEST_STATE_TONES: Record<RequestStateKind, string> = {
  idle: 'text-muted',
  loading: 'text-muted',
  connected: 'text-accent',
  error: 'text-critical',
  unavailable: 'text-warning',
};
