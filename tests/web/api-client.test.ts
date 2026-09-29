/**
 * The typed API client is the only place the web app performs HTTP.
 *
 * These tests prove that it talks to the versioned path, validates what it
 * receives, and reports network, HTTP and contract failures as three distinct
 * errors - never as success.
 */
import { describe, expect, it, vi } from 'vitest';

import { API_PATHS } from '@harsh-quant-os/shared';

import { ApiClientError, createApiClient } from '../../apps/web/src/api-client';
import fixture from '../contracts/datasets.json';

const HEALTH_PAYLOAD = {
  status: 'ok',
  service: 'harsh-quant-os-api',
  version: '0.1.0-alpha',
  environment: 'test',
};

const READY_PAYLOAD = {
  status: 'ready',
  service: 'harsh-quant-os-api',
  version: '0.1.0-alpha',
  environment: 'test',
  checks: [
    { name: 'api', status: 'ok', detail: 'application started and accepting HTTP requests' },
  ],
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('api client', () => {
  it('calls the versioned health path and returns the validated payload', async () => {
    const requested: string[] = [];
    const fetchImpl = vi.fn(async (url: string) => {
      requested.push(url);
      return jsonResponse(HEALTH_PAYLOAD);
    });
    const client = createApiClient({
      // A trailing slash must not produce a double slash in the request.
      baseUrl: 'http://127.0.0.1:8000/',
      fetch: fetchImpl,
    });

    const health = await client.getHealth();

    expect(health).toEqual(HEALTH_PAYLOAD);
    expect(requested).toEqual(['http://127.0.0.1:8000' + API_PATHS.health]);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('returns readiness with its checks', async () => {
    const client = createApiClient({
      baseUrl: 'http://127.0.0.1:8000',
      fetch: vi.fn(async (url: string) => {
        expect(url).toBe('http://127.0.0.1:8000' + API_PATHS.ready);
        return jsonResponse(READY_PAYLOAD);
      }),
    });

    const ready = await client.getReady();

    expect(ready.checks).toHaveLength(1);
    expect(ready.checks[0]?.name).toBe('api');
  });

  it('reports an unreachable API as a network error', async () => {
    const client = createApiClient({
      baseUrl: 'http://127.0.0.1:8000',
      fetch: vi.fn(async () => {
        throw new TypeError('fetch failed');
      }),
    });

    const error = await client.getHealth().catch((reason: unknown) => reason);

    expect(error).toBeInstanceOf(ApiClientError);
    const apiError = error as ApiClientError;
    expect(apiError.kind).toBe('network');
    expect(apiError.status).toBeNull();
    expect(apiError.message).toContain('Cannot reach the API');
  });

  it('reports an unhealthy response as an HTTP error with its status', async () => {
    const client = createApiClient({
      baseUrl: 'http://127.0.0.1:8000',
      fetch: vi.fn(async () => jsonResponse({ detail: 'boom' }, 503)),
    });

    const error = (await client.getHealth().catch((reason: unknown) => reason)) as ApiClientError;

    expect(error.kind).toBe('http');
    expect(error.status).toBe(503);
  });

  it('rejects a payload that does not match the contract', async () => {
    const client = createApiClient({
      baseUrl: 'http://127.0.0.1:8000',
      fetch: vi.fn(async () => jsonResponse({ status: 'healthy', service: 'x' })),
    });

    const error = (await client.getHealth().catch((reason: unknown) => reason)) as ApiClientError;

    expect(error.kind).toBe('contract');
    expect(error.cause).toBeInstanceOf(TypeError);
  });

  it('rejects a body that is not JSON', async () => {
    const client = createApiClient({
      baseUrl: 'http://127.0.0.1:8000',
      fetch: vi.fn(
        async () =>
          new Response('<!doctype html>', {
            status: 200,
            headers: { 'content-type': 'text/html' },
          }),
      ),
    });

    const error = (await client.getHealth().catch((reason: unknown) => reason)) as ApiClientError;

    expect(error.kind).toBe('contract');
  });
});

describe('api client — dataset reads', () => {
  // The shared Python/TypeScript fixture: real recorded metadata, so the
  // payloads here are observations rather than invented samples.
  const DIRECTORY = fixture.dataset_list;
  const DETAIL = fixture.dataset_detail;
  const BARS = fixture.dataset_bars;

  function clientReturning(payload: unknown): {
    client: ReturnType<typeof createApiClient>;
    requested: string[];
  } {
    const requested: string[] = [];
    const client = createApiClient({
      baseUrl: 'http://127.0.0.1:8000',
      fetch: vi.fn(async (url: string) => {
        requested.push(url);
        return jsonResponse(payload);
      }),
    });
    return { client, requested };
  }

  it('lists datasets from the versioned directory path', async () => {
    const { client, requested } = clientReturning(DIRECTORY);

    const response = await client.getDatasets();

    expect(response.datasets).toHaveLength(DIRECTORY.datasets.length);
    expect(response.datasets[0]?.name).toBe('kraken.xbtusd.1h');
    expect(requested).toEqual(['http://127.0.0.1:8000' + API_PATHS.datasets]);
  });

  it('reads one dataset by name', async () => {
    const { client, requested } = clientReturning(DETAIL);

    const response = await client.getDataset('kraken.xbtusd.1h');

    expect(response.dataset.version).toBe(DETAIL.dataset.version);
    expect(response.provenance.length).toBeGreaterThan(0);
    expect(requested).toEqual(['http://127.0.0.1:8000/api/v1/datasets/kraken.xbtusd.1h']);
  });

  it('encodes a dataset name containing a separator as one path component', async () => {
    const { client, requested } = clientReturning(DETAIL);

    await client.getDataset('example/pending');

    expect(requested).toEqual(['http://127.0.0.1:8000/api/v1/datasets/example%2Fpending']);
  });

  it('builds a bars URL from the parameters that were actually supplied', async () => {
    const { client, requested } = clientReturning(BARS);

    const response = await client.getDatasetBars('kraken.xbtusd.1h', {
      limit: 5,
      cursor: '2026-09-01T01:00:00Z',
    });

    expect(requested).toEqual([
      'http://127.0.0.1:8000/api/v1/datasets/kraken.xbtusd.1h/bars' +
        '?limit=5&cursor=2026-09-01T01%3A00%3A00Z',
    ]);
    expect(response.version).toBe(BARS.version);
    // The digits reach the caller as strings, exactly as stored.
    expect(response.bars[0]?.open).toBe('78563.0');
  });

  it('omits the query string entirely when no bars parameter is supplied', async () => {
    const { client, requested } = clientReturning(BARS);

    await client.getDatasetBars('kraken.xbtusd.1h');

    expect(requested).toEqual(['http://127.0.0.1:8000/api/v1/datasets/kraken.xbtusd.1h/bars']);
  });

  it('reports an unknown dataset as an HTTP error with its status', async () => {
    const client = createApiClient({
      baseUrl: 'http://127.0.0.1:8000',
      fetch: vi.fn(async () => jsonResponse({ detail: 'not found' }, 404)),
    });

    const error = (await client
      .getDataset('missing.dataset')
      .catch((reason: unknown) => reason)) as ApiClientError;

    expect(error.kind).toBe('http');
    expect(error.status).toBe(404);
  });

  it('rejects a dataset payload that does not match the contract', async () => {
    const client = createApiClient({
      baseUrl: 'http://127.0.0.1:8000',
      fetch: vi.fn(async () => jsonResponse({ datasets: 'not-a-list' })),
    });

    const error = (await client.getDatasets().catch((reason: unknown) => reason)) as ApiClientError;

    expect(error.kind).toBe('contract');
    expect(error.cause).toBeInstanceOf(TypeError);
  });
});
