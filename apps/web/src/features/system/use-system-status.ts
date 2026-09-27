'use client';

/**
 * Data hook behind the system status panel.
 *
 * The four states are exhaustive on purpose: loading, connected, error and
 * unavailable. There is no "assume healthy" branch - if the API cannot be
 * reached or answers with something that does not match the shared contract,
 * the UI says so.
 */
import { useEffect, useState } from 'react';

import type { HealthResponse } from '@harsh-quant-os/types';

import { ApiClientError, type ApiClient } from '../../api-client';

export type SystemStatusState =
  | { readonly kind: 'loading' }
  | { readonly kind: 'connected'; readonly health: HealthResponse }
  | { readonly kind: 'error'; readonly message: string }
  | { readonly kind: 'unavailable'; readonly message: string };

/** Map a client failure onto the state the UI should render. */
export function classifyError(error: unknown): SystemStatusState {
  if (error instanceof ApiClientError && error.kind === 'network') {
    return { kind: 'unavailable', message: error.message };
  }
  if (error instanceof ApiClientError) {
    return { kind: 'error', message: error.message };
  }
  return { kind: 'error', message: 'Unexpected failure while contacting the API.' };
}

/** Load `/health` once on mount and track the connection state. */
export function useSystemStatus(client: ApiClient): SystemStatusState {
  const [state, setState] = useState<SystemStatusState>({ kind: 'loading' });

  useEffect(() => {
    let active = true;
    const controller = new AbortController();

    setState({ kind: 'loading' });
    void client.getHealth({ signal: controller.signal }).then(
      (health) => {
        if (active) {
          setState({ kind: 'connected', health });
        }
      },
      (error: unknown) => {
        if (active) {
          setState(classifyError(error));
        }
      },
    );

    return () => {
      active = false;
      controller.abort();
    };
  }, [client]);

  return state;
}
