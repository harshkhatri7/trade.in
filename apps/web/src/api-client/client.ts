/**
 * The single place the web app talks to the API.
 *
 * Rules (docs/architecture/frontend.md):
 *
 * 1. Components never call `fetch`; they call an {@link ApiClient}.
 * 2. Every payload is validated against the shared contract before it is
 *    returned, so nothing unverified reaches the render tree.
 * 3. Failures are explicit. A network failure, an HTTP failure and a contract
 *    failure are three different things and the UI shows three different
 *    states - an unreachable API is never reported as healthy.
 */
import type { HealthResponse, ReadyResponse } from '@harsh-quant-os/types';
import { API_PATHS, parseHealthResponse, parseReadyResponse } from '@harsh-quant-os/shared';

import { resolveApiBaseUrl } from './config';

/** Why a request failed. `network` means the request never completed: the API
 * is stopped, the address is wrong, or the browser refused the response
 * (CORS). Browsers report all three the same way, so the message says so
 * rather than claiming one cause. */
export type ApiClientErrorKind = 'network' | 'http' | 'contract';

export interface ApiClientErrorOptions {
  readonly status?: number;
  readonly cause?: unknown;
}

export class ApiClientError extends Error {
  readonly kind: ApiClientErrorKind;
  /** HTTP status when the server answered, otherwise `null`. */
  readonly status: number | null;

  constructor(kind: ApiClientErrorKind, message: string, options: ApiClientErrorOptions = {}) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = 'ApiClientError';
    this.kind = kind;
    this.status = options.status ?? null;
  }
}

/** Injectable `fetch`, so tests can drive the client without a network. */
export type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

export interface RequestOptions {
  readonly signal?: AbortSignal;
}

export interface ApiClient {
  readonly baseUrl: string;
  getHealth(options?: RequestOptions): Promise<HealthResponse>;
  getReady(options?: RequestOptions): Promise<ReadyResponse>;
}

export interface CreateApiClientOptions {
  readonly baseUrl: string;
  readonly fetch?: FetchLike;
}

const defaultFetch: FetchLike = (url, init) => fetch(url, init);

function trimTrailingSlashes(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, '');
}

/** Build a client for one API base URL. */
export function createApiClient(options: CreateApiClientOptions): ApiClient {
  const baseUrl = trimTrailingSlashes(options.baseUrl);
  const fetchImpl: FetchLike = options.fetch ?? defaultFetch;

  async function request<T>(
    path: string,
    parse: (payload: unknown) => T,
    requestOptions?: RequestOptions,
  ): Promise<T> {
    const url = `${baseUrl}${path}`;

    let response: Response;
    try {
      response = await fetchImpl(url, {
        method: 'GET',
        headers: { Accept: 'application/json' },
        signal: requestOptions?.signal ?? null,
      });
    } catch (cause) {
      throw new ApiClientError(
        'network',
        `Cannot reach the API at ${baseUrl}: it is not running, the address is wrong, ` +
          'or the browser refused the response (CORS allow-list).',
        { cause },
      );
    }

    if (!response.ok) {
      throw new ApiClientError('http', `API responded with ${response.status} for ${path}`, {
        status: response.status,
      });
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch (cause) {
      throw new ApiClientError('contract', `API did not return JSON for ${path}`, {
        status: response.status,
        cause,
      });
    }

    try {
      return parse(payload);
    } catch (cause) {
      throw new ApiClientError('contract', `API response for ${path} failed validation`, {
        status: response.status,
        cause,
      });
    }
  }

  return {
    baseUrl,
    getHealth: (requestOptions) => request(API_PATHS.health, parseHealthResponse, requestOptions),
    getReady: (requestOptions) => request(API_PATHS.ready, parseReadyResponse, requestOptions),
  };
}

/** Client configured from `NEXT_PUBLIC_API_BASE_URL` (or its default). */
export const defaultApiClient: ApiClient = createApiClient({ baseUrl: resolveApiBaseUrl() });
