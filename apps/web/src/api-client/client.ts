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
import type {
  DatasetBarsResponse,
  DatasetDetailResponse,
  DatasetListResponse,
  HealthResponse,
  ReadyResponse,
} from '@harsh-quant-os/types';
import {
  API_PATHS,
  datasetBarsPath,
  datasetPath,
  parseDatasetBarsResponse,
  parseDatasetDetailResponse,
  parseDatasetListResponse,
  parseHealthResponse,
  parseReadyResponse,
} from '@harsh-quant-os/shared';

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

/**
 * Query parameters accepted by `GET /api/v1/datasets/{name}/bars`.
 *
 * All optional: the API applies its own default limit and bounds. What is
 * not supplied is left out of the URL entirely, so an absent parameter and
 * a defaulted one stay the same request.
 */
export interface DatasetBarsQuery {
  readonly limit?: number;
  /** ISO-8601 instant with a UTC offset; a naive timestamp is refused with 422. */
  readonly start?: string;
  /** ISO-8601 instant with a UTC offset; `end <= start` is refused with 422. */
  readonly end?: string;
  /** `next_cursor` from a previous page. */
  readonly cursor?: string;
}

export interface ApiClient {
  readonly baseUrl: string;
  getHealth(options?: RequestOptions): Promise<HealthResponse>;
  getReady(options?: RequestOptions): Promise<ReadyResponse>;
  /** Every dataset with provenance, quality status and version. */
  getDatasets(options?: RequestOptions): Promise<DatasetListResponse>;
  /** One dataset and its append-only acquisition history. */
  getDataset(name: string, options?: RequestOptions): Promise<DatasetDetailResponse>;
  /** A page of stored bars, tagged with the dataset version it was read from. */
  getDatasetBars(
    name: string,
    query?: DatasetBarsQuery,
    options?: RequestOptions,
  ): Promise<DatasetBarsResponse>;
}

export interface CreateApiClientOptions {
  readonly baseUrl: string;
  readonly fetch?: FetchLike;
}

const defaultFetch: FetchLike = (url, init) => fetch(url, init);

function trimTrailingSlashes(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, '');
}

/** Attach a query string, omitting every parameter that was not supplied. */
function withQuery(path: string, query?: DatasetBarsQuery): string {
  if (query === undefined) {
    return path;
  }
  const search = Object.entries(query)
    .filter((entry): entry is [string, string | number] => entry[1] !== undefined)
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    .join('&');
  return search.length > 0 ? `${path}?${search}` : path;
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
    getDatasets: (requestOptions) =>
      request(API_PATHS.datasets, parseDatasetListResponse, requestOptions),
    getDataset: (name, requestOptions) =>
      request(datasetPath(name), parseDatasetDetailResponse, requestOptions),
    getDatasetBars: (name, query, requestOptions) =>
      request(withQuery(datasetBarsPath(name), query), parseDatasetBarsResponse, requestOptions),
  };
}

/** Client configured from `NEXT_PUBLIC_API_BASE_URL` (or its default). */
export const defaultApiClient: ApiClient = createApiClient({ baseUrl: resolveApiBaseUrl() });
