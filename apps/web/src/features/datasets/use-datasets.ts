'use client';

/**
 * Data hooks behind the dataset browser.
 *
 * Three requests, three closed unions, and no branch that assumes a
 * payload:
 *
 * - the directory is `loading` → `connected` | `error` | `unavailable`;
 * - anything keyed by the selected dataset (provenance, bars) adds `idle`,
 *   because nothing is fetched until the operator picks a dataset and
 *   "not started yet" is a different fact from "failed".
 *
 * Every failure goes through the shared classifier in
 * `features/common/api-failure.ts`, so an unreachable API is never
 * rendered as a contract error and neither is ever rendered as data.
 * The name-keyed requests share one implementation whose loader is a
 * module-level constant, so the effect re-runs when the selection changes
 * and for no other reason.
 */
import { useEffect, useState } from 'react';

import type {
  DatasetBarsResponse,
  DatasetDetailResponse,
  DatasetListResponse,
} from '@harsh-quant-os/types';

import type { ApiClient } from '../../api-client';
import { classifyApiFailure } from '../common/api-failure';

export type DatasetListState =
  | { readonly kind: 'loading' }
  | { readonly kind: 'connected'; readonly response: DatasetListResponse }
  | { readonly kind: 'error'; readonly message: string }
  | { readonly kind: 'unavailable'; readonly message: string };

/** State of one request keyed by the selected dataset's name. */
export type DatasetResourceState<T> =
  | { readonly kind: 'idle' }
  | { readonly kind: 'loading' }
  | { readonly kind: 'connected'; readonly value: T }
  | { readonly kind: 'error'; readonly message: string }
  | { readonly kind: 'unavailable'; readonly message: string };

export type DatasetDetailState = DatasetResourceState<DatasetDetailResponse>;
export type DatasetBarsState = DatasetResourceState<DatasetBarsResponse>;

/**
 * Rows requested for the chart. The API caps a page at 5000; 200 is a
 * window, not the series — `has_more` in the response says so out loud,
 * and the panel renders that rather than implying the chart is complete.
 */
export const BARS_LIMIT = 200;

type Loader<T> = (client: ApiClient, name: string, signal: AbortSignal) => Promise<T>;

/** Load `GET /api/v1/datasets` once on mount and track the request state. */
export function useDatasetList(client: ApiClient): DatasetListState {
  const [state, setState] = useState<DatasetListState>({ kind: 'loading' });

  useEffect(() => {
    let active = true;
    const controller = new AbortController();

    setState({ kind: 'loading' });
    void client.getDatasets({ signal: controller.signal }).then(
      (response) => {
        if (active) {
          setState({ kind: 'connected', response });
        }
      },
      (error: unknown) => {
        if (active) {
          setState(classifyApiFailure(error));
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

/**
 * Fetch `load` whenever `name` is selected; `null` returns to `idle`.
 *
 * The previous request is aborted on change or unmount, so a stale answer
 * can never overwrite a newer selection.
 */
function useNamedResource<T>(
  client: ApiClient,
  name: string | null,
  load: Loader<T>,
): DatasetResourceState<T> {
  const [state, setState] = useState<DatasetResourceState<T>>({ kind: 'idle' });

  useEffect(() => {
    if (name === null) {
      setState({ kind: 'idle' });
      return undefined;
    }

    let active = true;
    const controller = new AbortController();

    setState({ kind: 'loading' });
    void load(client, name, controller.signal).then(
      (value) => {
        if (active) {
          setState({ kind: 'connected', value });
        }
      },
      (error: unknown) => {
        if (active) {
          setState(classifyApiFailure(error));
        }
      },
    );

    return () => {
      active = false;
      controller.abort();
    };
  }, [client, name, load]);

  return state;
}

const loadDetail: Loader<DatasetDetailResponse> = (client, name, signal) =>
  client.getDataset(name, { signal });

const loadBars: Loader<DatasetBarsResponse> = (client, name, signal) =>
  client.getDatasetBars(name, { limit: BARS_LIMIT }, { signal });

/** `GET /api/v1/datasets/{name}` — summary plus append-only provenance. */
export function useDatasetDetail(client: ApiClient, name: string | null): DatasetDetailState {
  return useNamedResource(client, name, loadDetail);
}

/** `GET /api/v1/datasets/{name}/bars` — one page of stored bars. */
export function useDatasetBars(client: ApiClient, name: string | null): DatasetBarsState {
  return useNamedResource(client, name, loadBars);
}
