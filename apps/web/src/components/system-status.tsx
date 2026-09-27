'use client';

/**
 * System status panel: API connection, version and environment.
 *
 * Every value displayed here comes from a validated `/health` response. The
 * labels are derived from the request state, so "CONNECTED" cannot appear
 * unless the API actually answered, and an unreachable API renders as
 * "DISCONNECTED" rather than being hidden.
 */
import type { HealthResponse } from '@harsh-quant-os/types';

import type { ApiClient } from '../api-client';
import { defaultApiClient } from '../api-client';
import { useSystemStatus } from '../features/system/use-system-status';
import type { SystemStatusState } from '../features/system/use-system-status';

export interface SystemStatusProps {
  /** Injected in tests; production uses the configured default client. */
  readonly client?: ApiClient;
}

const STATUS_LABELS: Record<SystemStatusState['kind'], string> = {
  loading: 'LOADING',
  connected: 'CONNECTED',
  error: 'ERROR',
  unavailable: 'DISCONNECTED',
};

const STATUS_TONES: Record<SystemStatusState['kind'], string> = {
  loading: 'text-muted',
  connected: 'text-accent',
  error: 'text-critical',
  unavailable: 'text-warning',
};

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
    <div className="flex items-baseline justify-between gap-4 border-b border-line py-3 last:border-b-0">
      <dt className="text-xs uppercase tracking-[0.18em] text-muted">{label}</dt>
      <dd className="font-mono text-sm tabular-nums text-ink">{value}</dd>
    </div>
  );
}

export function SystemStatus({ client = defaultApiClient }: SystemStatusProps) {
  const state = useSystemStatus(client);
  const health: HealthResponse | null = state.kind === 'connected' ? state.health : null;

  return (
    <section
      aria-labelledby="system-status-heading"
      data-state={state.kind}
      className="rounded-lg border border-line bg-raised p-6 sm:p-8"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="system-status-heading" className="text-lg font-semibold tracking-tight">
          System status
        </h2>
        <p className="text-xs uppercase tracking-[0.18em] text-muted">Live API response</p>
      </div>

      <dl className="mt-6">
        <div className="flex items-baseline justify-between gap-4 border-b border-line py-3">
          <dt className="text-xs uppercase tracking-[0.18em] text-muted">API</dt>
          <dd className={STATUS_TONES[state.kind]}>
            <span role="status" className="font-mono text-sm font-semibold tracking-wide">
              {STATUS_LABELS[state.kind]}
            </span>
          </dd>
        </div>
        <Row label="Version" value={health ? health.version : '—'} />
        <Row label="Environment" value={health ? health.environment : '—'} />
        <Row label="Endpoint" value={client.baseUrl} />
      </dl>

      {state.kind === 'error' || state.kind === 'unavailable' ? (
        // The underlying failure is shown as it happened: a network error, an
        // HTTP status or a contract violation is never reduced to a generic
        // reassurance.
        <p className={'mt-4 text-sm ' + STATUS_TONES[state.kind]} data-detail={state.kind}>
          {state.message}
        </p>
      ) : (
        <p className="mt-4 text-sm text-muted">{STATUS_NOTES[state.kind]}</p>
      )}
    </section>
  );
}
