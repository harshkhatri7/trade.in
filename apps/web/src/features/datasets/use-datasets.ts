'use client';

/**
 * Data hooks behind the dataset browser.
 *
 * Two requests, two closed unions, and no branch that assumes a payload:
 *
 * - the directory is `loading` → `connected` | `error` | `unavailable`;
 * - the detail request adds `idle`, because nothing is fetched until the
 *   operator picks a dataset and "not started yet" is a different fact
 *   from "failed".
 *
 * Every failure goes through the shared classifier in
 * `features/common/api-failure.ts`, so an unreachable API is never
 * rendered as a contract error and neither is ever rendered as data.
 */
import { useEffect, useState } from 'react';

import type { DatasetDetailResponse, DatasetListResponse } from '@harsh-quant-os/types';

import type { ApiClient } from '../../api-client';
import { classifyApiFailure } from '../common/api-failure';

export type DatasetListState =
  | { readonly kind: 'loading' }
  | { readonly kind: 'connected'; readonly response: DatasetListResponse }
  | { readonly kind: 'error'; readonly message: string }
  | { readonly kind: 'unavailable'; readonly message: string };

export type DatasetDetailState =
  | { readonly kind: 'idle' }
  | { readonly kind: 'loading' }
  | { readonly kind: 'connected'; readonly detail: DatasetDetailResponse }
  | { readonly kind: 'error'; readonly message: string }
  | { readonly kind: 'unavailable'; readonly message: string };

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
 * Load `GET /api/v1/datasets/{name}` for the selected dataset.
 *
 * Selecting `null` returns to `idle` and the previous request is aborted,
 * so a stale provenance answer can never overwrite a newer selection.
 */
export function useDatasetDetail(client: ApiClient, name: string | null): DatasetDetailState {
  const [state, setState] = useState<DatasetDetailState>({ kind: 'idle' });

  useEffect(() => {
    if (name === null) {
      setState({ kind: 'idle' });
      return undefined;
    }

    let active = true;
    const controller = new AbortController();

    setState({ kind: 'loading' });
    void client.getDataset(name, { signal: controller.signal }).then(
      (detail) => {
        if (active) {
          setState({ kind: 'connected', detail });
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
  }, [client, name]);

  return state;
}
