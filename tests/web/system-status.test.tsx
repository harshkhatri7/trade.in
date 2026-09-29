/**
 * @vitest-environment jsdom
 *
 * The status panel must render the state it is given - and must never claim a
 * connection that did not happen. Each state (loading, connected, error,
 * unavailable) has its own assertion here.
 */
import { afterEach, describe, expect, it } from 'vitest';

import { cleanup, render, screen } from '@testing-library/react';

import type { HealthResponse } from '@harsh-quant-os/types';

import type { ApiClient } from '../../apps/web/src/api-client';
import { ApiClientError } from '../../apps/web/src/api-client';
import { SystemStatus } from '../../apps/web/src/components/system-status';

const BASE_URL = 'http://127.0.0.1:8000';

const HEALTH: HealthResponse = {
  status: 'ok',
  service: 'harsh-quant-os-api',
  version: '0.1.0-alpha',
  environment: 'test',
};

function clientWith(getHealth: ApiClient['getHealth']): ApiClient {
  const unused = () => Promise.reject(new Error('not used in this test'));
  return {
    baseUrl: BASE_URL,
    getHealth,
    getReady: unused,
    getDatasets: unused,
    getDataset: unused,
    getDatasetBars: unused,
  };
}

// Vitest runs without globals here, so React Testing Library cannot register
// its own auto-cleanup. Without this, DOM from a previous test would leak into
// the next one and make assertions pass or fail for the wrong reason.
afterEach(() => {
  cleanup();
});

describe('<SystemStatus />', () => {
  it('shows the loading state while the API has not answered', () => {
    const client = clientWith(() => new Promise<HealthResponse>(() => undefined));

    render(<SystemStatus client={client} />);

    expect(screen.getByRole('status').textContent).toBe('LOADING');
    expect(screen.queryByText('CONNECTED')).toBeNull();
    // Version and environment are both unknown while loading.
    expect(screen.getAllByText('—')).toHaveLength(2);
  });

  it('renders the values returned by the API when it answers', async () => {
    const client = clientWith(() => Promise.resolve(HEALTH));

    render(<SystemStatus client={client} />);

    expect((await screen.findByText('CONNECTED')).textContent).toBe('CONNECTED');
    expect(screen.getByText(HEALTH.version)).toBeTruthy();
    expect(screen.getByText(HEALTH.environment)).toBeTruthy();
    expect(screen.getByText(BASE_URL)).toBeTruthy();
  });

  it('shows DISCONNECTED when the API cannot be reached', async () => {
    const client = clientWith(() =>
      Promise.reject(new ApiClientError('network', `Cannot reach the API at ${BASE_URL}`)),
    );

    render(<SystemStatus client={client} />);

    expect((await screen.findByText('DISCONNECTED')).textContent).toBe('DISCONNECTED');
    expect(screen.queryByText('CONNECTED')).toBeNull();
    // No response means no version and no environment - they stay unknown.
    expect(screen.getAllByText('—')).toHaveLength(2);
  });

  it('shows ERROR when the API answers with something unusable', async () => {
    const client = clientWith(() =>
      Promise.reject(
        new ApiClientError('http', 'API responded with 503 for /api/v1/health', {
          status: 503,
        }),
      ),
    );

    render(<SystemStatus client={client} />);

    expect((await screen.findByText('ERROR')).textContent).toBe('ERROR');
    expect(screen.queryByText('CONNECTED')).toBeNull();
  });

  it('does not invent a version when no response arrived', () => {
    const client = clientWith(() => new Promise<HealthResponse>(() => undefined));

    render(<SystemStatus client={client} />);

    expect(screen.queryByText(HEALTH.version)).toBeNull();
    expect(screen.queryByText('0.1.0')).toBeNull();
  });

  it('shows the underlying failure instead of a generic reassurance', async () => {
    const message = 'Cannot reach the API at http://127.0.0.1:8000: it is not running';
    const client = clientWith(() => Promise.reject(new ApiClientError('network', message)));

    render(<SystemStatus client={client} />);

    expect((await screen.findByText(message)).textContent).toBe(message);
    expect(screen.queryByText('Response validated against the shared contract.')).toBeNull();
  });

  it('marks the section with the state it is in', async () => {
    const client = clientWith(() => Promise.resolve(HEALTH));

    const { container } = render(<SystemStatus client={client} />);

    expect(container.querySelector('[data-state]')?.getAttribute('data-state')).toBe('loading');
    await screen.findByText('CONNECTED');
    expect(container.querySelector('[data-state]')?.getAttribute('data-state')).toBe('connected');
  });
});
