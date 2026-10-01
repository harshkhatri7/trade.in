'use client';

/**
 * System status panel: API connection, version and environment.
 *
 * Every value displayed here comes from a validated `/health` response. The
 * labels are derived from the request state, so "CONNECTED" cannot appear
 * unless the API actually answered, and an unreachable API renders as
 * "DISCONNECTED" rather than being hidden.
 *
 * Visual notes: the state word is rendered as a chip whose tint is backed
 * by a dot *and* the word itself, so colour is never the only signal; the
 * skeleton shown while loading is decorative and `aria-hidden`, because
 * the `LOADING` status is the announcement. There is exactly one
 * `role="status"` in this panel — the state chip — so assistive tech
 * receives one announcement per state change rather than a chorus.
 */
import type { HealthResponse } from '@harsh-quant-os/types';

import type { ApiClient } from '../api-client';
import { defaultApiClient } from '../api-client';
import { REQUEST_STATE_LABELS, REQUEST_STATE_TONES } from '../features/common/request-state';
import { useSystemStatus } from '../features/system/use-system-status';

export interface SystemStatusProps {
  /** Injected in tests; production uses the configured default client. */
  readonly client?: ApiClient;
}

/**
 * Copy for the two states that have no failure to report. `error` and
 * `unavailable` render the real message instead, so they have no note here.
 */
const STATUS_NOTES: Record<'loading' | 'connected', string> = {
  loading: 'Waiting for the API to answer…',
  connected: 'Response validated against the shared contract.',
};

function Row({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-white/5 py-3 last:border-b-0">
      <dt className="eyebrow">{label}</dt>
      <dd className="font-mono text-sm tabular-nums text-ink">{value}</dd>
    </div>
  );
}

export function SystemStatus({ client = defaultApiClient }: SystemStatusProps) {
  const state = useSystemStatus(client);
  const health: HealthResponse | null = state.kind === 'connected' ? state.health : null;

  return (
    <section aria-labelledby="system-status-heading" data-state={state.kind} className="panel">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="system-status-heading" className="panel-title">
          System status
        </h2>
        <p className="eyebrow">Live API response</p>
      </div>

      <dl className="mt-6">
        <div className="flex items-baseline justify-between gap-4 border-b border-white/5 py-3">
          <dt className="eyebrow">API</dt>
          <dd className={REQUEST_STATE_TONES[state.kind]}>
            <span role="status" className="state-chip">
              {REQUEST_STATE_LABELS[state.kind]}
            </span>
          </dd>
        </div>
        <Row label="Version" value={health ? health.version : '—'} />
        <Row label="Environment" value={health ? health.environment : '—'} />
        <Row label="Endpoint" value={client.baseUrl} />
      </dl>

      {state.kind === 'loading' && (
        // Decorative only: three shimmering bars stand in for the rows that
        // have not arrived. The real announcement is the LOADING chip above.
        <div className="mt-4 space-y-2" aria-hidden="true">
          <div className="skeleton h-4 w-2/3" />
          <div className="skeleton h-4 w-1/2" />
          <div className="skeleton h-4 w-3/5" />
        </div>
      )}

      {(state.kind === 'error' || state.kind === 'unavailable') && (
        // The underlying failure is shown as it happened: a network error, an
        // HTTP status or a contract violation is never reduced to a generic
        // reassurance.
        <p
          className={'note mt-4 ' + REQUEST_STATE_TONES[state.kind]}
          data-detail={state.kind}
          role="note"
        >
          {state.message}
        </p>
      )}

      {(state.kind === 'loading' || state.kind === 'connected') && (
        <p className="note mt-4">{STATUS_NOTES[state.kind]}</p>
      )}
    </section>
  );
}
