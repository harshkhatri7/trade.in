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

import type {
  DatasetBarsResponse,
  DatasetDetailResponse,
  DatasetListResponse,
} from '@harsh-quant-os/types';

import { ApiClientError, type ApiClient } from '../../apps/web/src/api-client';
import { DatasetBrowser } from '../../apps/web/src/components/dataset-browser';
import fixture from '../contracts/datasets.json';

// jsdom provides no canvas and no `matchMedia`, which the real chart library
// requires; these tests exercise the browser's data flow, not chart pixels.
// The data handed to the chart is asserted in dataset-bars.test.tsx.
vi.mock('lightweight-charts', () => ({
  createChart: vi.fn(() => ({
    addSeries: vi.fn(() => ({ setData: vi.fn() })),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
    remove: vi.fn(),
  })),
  CandlestickSeries: Symbol('CandlestickSeries'),
  ColorType: { Solid: 'solid' },
}));

const BASE_URL = 'http://127.0.0.1:8000';

const DIRECTORY = fixture.dataset_list as DatasetListResponse;
const DETAIL = fixture.dataset_detail as DatasetDetailResponse;
const BARS = fixture.dataset_bars as DatasetBarsResponse;

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
// the next one and make assertions pass or fail for the wrong reason. The
// watchlist persists to localStorage, which outlives `cleanup()` inside this
// file — it is cleared so no test inherits another test's follows.
afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe('<DatasetBrowser />', () => {
  it('shows the loading state until the directory arrives', () => {
    const client = clientWith({
      getDatasets: () => new Promise<DatasetListResponse>(() => undefined),
    });

    render(<DatasetBrowser client={client} />);

    const directory = screen.getByRole('region', { name: 'Dataset directory' });
    expect(directory.getAttribute('data-state')).toBe('loading');
    // Scoped to the directory: the watchlist and multi-timeframe panels
    // legitimately show their own state word for the same request.
    expect(within(directory).getByText('LOADING')).toBeTruthy();
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

    // Scoped to the directory: the watchlist and multi-timeframe panels show
    // their own state word for the same failed request.
    const directory = screen.getByRole('region', { name: 'Dataset directory' });
    expect((await within(directory).findByText('ERROR')).textContent).toBe('ERROR');
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

    // Scoped to the directory: the watchlist and multi-timeframe panels show
    // their own state word for the same failed request.
    const directory = screen.getByRole('region', { name: 'Dataset directory' });
    expect((await within(directory).findByText('DISCONNECTED')).textContent).toBe('DISCONNECTED');
    expect(screen.getByText(message)).toBeTruthy();
    expect(screen.queryByText('CONNECTED')).toBeNull();
  });

  it('loads provenance for the selected dataset and names its full version', async () => {
    const getDataset = vi.fn(() => Promise.resolve(DETAIL));
    const client = clientWith({
      getDatasets: () => Promise.resolve(DIRECTORY),
      getDataset,
      getDatasetBars: () => Promise.resolve(BARS),
    });

    render(<DatasetBrowser client={client} />);

    await screen.findByText('2 dataset(s) listed.');
    fireEvent.click(screen.getByRole('button', { name: 'kraken.xbtusd.1h' }));

    expect(getDataset).toHaveBeenCalledWith('kraken.xbtusd.1h', expect.anything());

    await screen.findByText('2 acquisition record(s), newest first.');
    // The bars panel fires with the same selection; wait for its answer so
    // the shared-version assertion below is not a race between two requests.
    await screen.findByText('2 bar(s) in this window.');

    const detail = screen.getByRole('region', { name: 'kraken.xbtusd.1h' });
    expect(detail.getAttribute('data-state')).toBe('connected');
    // The full SHA-256 is on screen: a figure can name its artefact exactly.
    // It appears twice — beside the summary and above the chart — and both
    // must carry the same value.
    expect(within(detail).getAllByText(FULL_VERSION).length).toBe(2);
    expect(
      within(detail).getByText(
        '28 bar(s) flagged as outliers; values are reported as found, not adjusted',
      ),
    ).toBeTruthy();
    // The instrument is asserted inside the panel: it also appears in the
    // directory row (and now in the bars metadata line), so it is looked up
    // in bulk here rather than mistaken for a unique match.
    expect(within(detail).getAllByText('XBTUSD').length).toBeGreaterThanOrEqual(2);
    expect(
      screen.getByRole('button', { name: 'kraken.xbtusd.1h' }).getAttribute('aria-pressed'),
    ).toBe('true');
    // The bars panel opened with the selection, and it is charting the same
    // dataset version as the summary above it.
    const bars = screen.getByRole('region', { name: 'Stored bars' });
    expect(bars.getAttribute('data-state')).toBe('connected');
    expect(within(bars).getAllByText(FULL_VERSION).length).toBe(1);
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
      getDatasetBars: () => Promise.resolve(BARS),
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

  it('follows a dataset into the watchlist and opens it from there', async () => {
    const getDataset = vi.fn(() => Promise.resolve(DETAIL));
    const client = clientWith({
      getDatasets: () => Promise.resolve(DIRECTORY),
      getDataset,
      getDatasetBars: () => Promise.resolve(BARS),
    });

    render(<DatasetBrowser client={client} />);

    await screen.findByText('2 dataset(s) listed.');

    // Both panels are part of the page and follow the directory's state.
    const watchlist = screen.getByRole('region', { name: 'Watchlist' });
    const multi = screen.getByRole('region', { name: 'Multi-timeframe views' });
    expect(watchlist.getAttribute('data-state')).toBe('connected');
    expect(multi.getAttribute('data-state')).toBe('connected');
    expect(within(watchlist).getByText(/No datasets followed yet/)).toBeTruthy();

    // Follow from the directory row: the toggle reports pressed, and the
    // watchlist panel below gains the row — one state, two controls.
    const follow = screen.getByRole('button', { name: 'Follow kraken.xbtusd.1h' });
    expect(follow.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(follow);
    expect(follow.getAttribute('aria-pressed')).toBe('true');
    expect(within(watchlist).getByText('kraken.xbtusd.1h')).toBeTruthy();

    // Opening from the watchlist uses the same handler as a directory row.
    fireEvent.click(within(watchlist).getByRole('button', { name: 'Open kraken.xbtusd.1h' }));
    await screen.findByText('2 acquisition record(s), newest first.');
    expect(getDataset).toHaveBeenCalledWith('kraken.xbtusd.1h', expect.anything());

    // Unfollow from the watchlist: the row leaves and the directory toggle
    // resets — both controls still report the same single state.
    fireEvent.click(
      within(watchlist).getByRole('button', { name: 'Remove kraken.xbtusd.1h from the watchlist' }),
    );
    expect(within(watchlist).getByText(/No datasets followed yet/)).toBeTruthy();
    expect(follow.getAttribute('aria-pressed')).toBe('false');
  });

  it('offers only the stored timeframe for an instrument in the multi-timeframe panel', async () => {
    const client = clientWith({ getDatasets: () => Promise.resolve(DIRECTORY) });

    render(<DatasetBrowser client={client} />);

    await screen.findByText('2 dataset(s) listed.');

    const multi = screen.getByRole('region', { name: 'Multi-timeframe views' });
    // XBTUSD has exactly one stored timeframe in the fixture; every other
    // canonical timeframe is shown but not offered as a link to nothing.
    const open = within(multi).getByRole('button', { name: 'View 1h of XBTUSD' });
    expect(open.textContent).toBe('1h');
    expect(within(multi).queryByRole('button', { name: 'View 1d of XBTUSD' })).toBeNull();
    expect(within(multi).getAllByText('(not stored)').length).toBeGreaterThan(0);
    // The dataset that cannot be placed on the grid is named, not dropped.
    expect(within(multi).getByText(/example\.pending\.1d/)).toBeTruthy();
  });
});
