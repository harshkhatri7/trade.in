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
