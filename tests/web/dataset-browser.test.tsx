/**
 * @vitest-environment jsdom
 *
 * The dataset browser must render only validated payloads, keep its request
 * states explicit, and never turn a missing field into zero. The payloads
 * are the shared Python/TypeScript fixture: real recorded metadata, so
 * nothing here is an invented sample.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';

import type { DatasetDetailResponse, DatasetListResponse } from '@harsh-quant-os/types';

import { ApiClientError, type ApiClient } from '../../apps/web/src/api-client';
import { DatasetBrowser } from '../../apps/web/src/components/dataset-browser';
import fixture from '../contracts/datasets.json';

const BASE_URL = 'http://127.0.0.1:8000';

const DIRECTORY = fixture.dataset_list as DatasetListResponse;
const DETAIL = fixture.dataset_detail as DatasetDetailResponse;

const FULL_VERSION = '0f27a08bfb355c898c0b8948da590c50dc612371599e34675f56c72ea8393883';

function clientWith(overrides: Partial<ApiClient>): ApiClient {
  const unused = () => Promise.reject(new Error('not used in this test'));
  return {
    baseUrl: BASE_URL,
    getHealth: unused,
    getReady: unused,
    getDatasets: unused,
    getDataset: unused,
    getDatasetBars: unused,
    ...overrides,
  };
}

// Vitest runs without globals here, so React Testing Library cannot register
// its own auto-cleanup. Without this, DOM from a previous test would leak into
// the next one and make assertions pass or fail for the wrong reason.
afterEach(() => {
  cleanup();
});

describe('<DatasetBrowser />', () => {
  it('shows the loading state until the directory arrives', () => {
    const client = clientWith({
      getDatasets: () => new Promise<DatasetListResponse>(() => undefined),
    });

    render(<DatasetBrowser client={client} />);

    const directory = screen.getByRole('region', { name: 'Dataset directory' });
    expect(directory.getAttribute('data-state')).toBe('loading');
    expect(screen.getByText('LOADING')).toBeTruthy();
    // Nothing may appear as data before a validated payload arrives.
    expect(screen.queryByText('kraken.xbtusd.1h')).toBeNull();
    expect(screen.queryByText('649')).toBeNull();
  });

  it('renders the directory with quality, rows and version once it answers', async () => {
    const client = clientWith({ getDatasets: () => Promise.resolve(DIRECTORY) });

    render(<DatasetBrowser client={client} />);

    await screen.findByText('2 dataset(s) listed.');

    const directory = screen.getByRole('region', { name: 'Dataset directory' });
    expect(directory.getAttribute('data-state')).toBe('connected');
    expect(screen.getByText('kraken.xbtusd.1h')).toBeTruthy();
    expect(screen.getByText('example.pending.1d')).toBeTruthy();
    expect(screen.getByText('suspect')).toBeTruthy();
    expect(screen.getByText('649')).toBeTruthy();
    // The directory shows a shortened version; the detail panel shows it in full.
    expect(screen.getByText('0f27a08bfb35…')).toBeTruthy();
  });

  it('shows a dash for a field that was never recorded, never zero', async () => {
    const client = clientWith({ getDatasets: () => Promise.resolve(DIRECTORY) });

    render(<DatasetBrowser client={client} />);

    await screen.findByText('2 dataset(s) listed.');

    // `example.pending.1d` carries nulls for instrument, timeframe, version,
    // source, acquisition time and row count. None of them may become 0.
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    expect(screen.queryByText('0')).toBeNull();
  });

  it('says plainly when no dataset is registered, without pretending an error', async () => {
    const client = clientWith({ getDatasets: () => Promise.resolve({ datasets: [] }) });

    render(<DatasetBrowser client={client} />);

    await screen.findByText('No datasets are registered in this workspace yet.');

    const directory = screen.getByRole('region', { name: 'Dataset directory' });
    expect(directory.getAttribute('data-state')).toBe('connected');
    expect(screen.queryByText('ERROR')).toBeNull();
    expect(screen.queryByText('DISCONNECTED')).toBeNull();
  });

  it('shows ERROR with the exact failure when the API answers unusably', async () => {
    const client = clientWith({
      getDatasets: () =>
        Promise.reject(
          new ApiClientError('http', 'API responded with 500 for /api/v1/datasets', {
            status: 500,
          }),
        ),
    });

    render(<DatasetBrowser client={client} />);

    expect((await screen.findByText('ERROR')).textContent).toBe('ERROR');
    expect(screen.getByText('API responded with 500 for /api/v1/datasets')).toBeTruthy();
    expect(screen.queryByText('CONNECTED')).toBeNull();
    expect(screen.queryByText('649')).toBeNull();
  });

  it('shows DISCONNECTED when the API cannot be reached', async () => {
    const message =
      'Cannot reach the API at http://127.0.0.1:8000: it is not running, the address is ' +
      'wrong, or the browser refused the response (CORS allow-list).';
    const client = clientWith({
      getDatasets: () => Promise.reject(new ApiClientError('network', message)),
    });

    render(<DatasetBrowser client={client} />);

    expect((await screen.findByText('DISCONNECTED')).textContent).toBe('DISCONNECTED');
    expect(screen.getByText(message)).toBeTruthy();
    expect(screen.queryByText('CONNECTED')).toBeNull();
  });

  it('loads provenance for the selected dataset and names its full version', async () => {
    const getDataset = vi.fn(() => Promise.resolve(DETAIL));
    const client = clientWith({
      getDatasets: () => Promise.resolve(DIRECTORY),
      getDataset,
    });

    render(<DatasetBrowser client={client} />);

    await screen.findByText('2 dataset(s) listed.');
    fireEvent.click(screen.getByRole('button', { name: 'kraken.xbtusd.1h' }));

    expect(getDataset).toHaveBeenCalledWith('kraken.xbtusd.1h', expect.anything());

    await screen.findByText('2 acquisition record(s), newest first.');

    const detail = screen.getByRole('region', { name: 'kraken.xbtusd.1h' });
    expect(detail.getAttribute('data-state')).toBe('connected');
    // The full SHA-256 is on screen: a figure can name its artefact exactly.
    expect(within(detail).getAllByText(FULL_VERSION).length).toBeGreaterThan(0);
    expect(
      within(detail).getByText(
        '28 bar(s) flagged as outliers; values are reported as found, not adjusted',
      ),
    ).toBeTruthy();
    // The instrument is asserted inside the panel: it also appears in the
    // directory row, and the two must not be confused for each other.
    expect(within(detail).getByText('XBTUSD')).toBeTruthy();
    expect(
      screen.getByRole('button', { name: 'kraken.xbtusd.1h' }).getAttribute('aria-pressed'),
    ).toBe('true');
  });

  it('keeps the directory visible when one provenance request fails', async () => {
    const client = clientWith({
      getDatasets: () => Promise.resolve(DIRECTORY),
      getDataset: () =>
        Promise.reject(
          new ApiClientError(
            'http',
            'API responded with 404 for /api/v1/datasets/kraken.xbtusd.1h',
            {
              status: 404,
            },
          ),
        ),
    });

    render(<DatasetBrowser client={client} />);

    await screen.findByText('2 dataset(s) listed.');
    fireEvent.click(screen.getByRole('button', { name: 'kraken.xbtusd.1h' }));

    await screen.findByText('API responded with 404 for /api/v1/datasets/kraken.xbtusd.1h');

    const directory = screen.getByRole('region', { name: 'Dataset directory' });
    expect(directory.getAttribute('data-state')).toBe('connected');
    const detail = screen.getByRole('region', { name: 'kraken.xbtusd.1h' });
    expect(detail.getAttribute('data-state')).toBe('error');
  });

  it('returns to the directory when the detail panel is closed', async () => {
    const client = clientWith({
      getDatasets: () => Promise.resolve(DIRECTORY),
      getDataset: () => Promise.resolve(DETAIL),
    });

    render(<DatasetBrowser client={client} />);

    await screen.findByText('2 dataset(s) listed.');
    fireEvent.click(screen.getByRole('button', { name: 'kraken.xbtusd.1h' }));
    await screen.findByText('2 acquisition record(s), newest first.');

    fireEvent.click(screen.getByRole('button', { name: 'Close' }));

    expect(screen.queryByRole('region', { name: 'kraken.xbtusd.1h' })).toBeNull();
    expect(
      screen.getByRole('button', { name: 'kraken.xbtusd.1h' }).getAttribute('aria-pressed'),
    ).toBe('false');
  });
});
