/**
 * @vitest-environment jsdom
 *
 * The bars panel must chart exactly what it prints, keep every request
 * state explicit, and never let a converted number reach the table. The
 * chart needs a canvas, which jsdom does not provide, so the library is
 * stubbed here and these tests assert the data handed to it; the rendered
 * chart is verified in a real browser rather than faked here. Payloads are
 * the shared Python/TypeScript fixture: real recorded bars.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { cleanup, render, screen, waitFor, within } from '@testing-library/react';

import type { DatasetBarsResponse } from '@harsh-quant-os/types';

import { ApiClientError, type ApiClient } from '../../apps/web/src/api-client';
import { DatasetBars } from '../../apps/web/src/components/dataset-bars';
import fixture from '../contracts/datasets.json';

const setDataMock = vi.hoisted(() => vi.fn());

vi.mock('lightweight-charts', () => {
  const series = { setData: setDataMock };
  const chart = {
    addSeries: vi.fn(() => series),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
    remove: vi.fn(),
  };
  return {
    createChart: vi.fn(() => chart),
    CandlestickSeries: Symbol('CandlestickSeries'),
    ColorType: { Solid: 'solid' },
  };
});

const BASE_URL = 'http://127.0.0.1:8000';

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
// the next one and make assertions pass or fail for the wrong reason.
afterEach(() => {
  cleanup();
  setDataMock.mockClear();
});

describe('<DatasetBars />', () => {
  it('stays in the loading state until the bars arrive', () => {
    const getDatasetBars = vi.fn(() => new Promise<DatasetBarsResponse>(() => undefined));
    const client = clientWith({ getDatasetBars });

    render(<DatasetBars name="kraken.xbtusd.1h" client={client} />);

    const panel = screen.getByRole('region', { name: 'Stored bars' });
    expect(panel.getAttribute('data-state')).toBe('loading');
    expect(screen.getByText('LOADING')).toBeTruthy();
    // Nothing may be drawn or printed before a validated payload arrives.
    expect(screen.queryByRole('figure')).toBeNull();
    expect(screen.queryByText('78563.0')).toBeNull();
    // The window is requested explicitly: this is a page, not the series.
    expect(getDatasetBars).toHaveBeenCalledWith(
      'kraken.xbtusd.1h',
      { limit: 200 },
      expect.anything(),
    );
  });

  it('charts and prints the same bars, with the version naming the artefact', async () => {
    const client = clientWith({ getDatasetBars: () => Promise.resolve(BARS) });

    render(<DatasetBars name="kraken.xbtusd.1h" client={client} />);

    await screen.findByText('2 bar(s) in this window.');

    const panel = screen.getByRole('region', { name: 'Stored bars' });
    expect(panel.getAttribute('data-state')).toBe('connected');

    // The version the payload carries is on screen in full, above the figure.
    expect(within(panel).getAllByText(FULL_VERSION).length).toBeGreaterThan(0);
    expect(within(panel).getByText(/Instrument/)).toBeTruthy();
    expect(within(panel).getByText(/quality/i)).toBeTruthy();

    // The chart is a labelled figure (not `img`: the library's attribution
    // link lives inside, and `img` is a leaf role) stating what it holds.
    const chart = screen.getByRole('figure');
    expect(chart.getAttribute('aria-label')).toContain('Candlestick chart of kraken.xbtusd.1h');
    expect(chart.getAttribute('aria-label')).toContain('2 stored bars');

    // What the chart received: converted numbers on epoch seconds, because
    // canvas geometry cannot be drawn from decimal strings. The chart is
    // built in a passive effect, so the assertion waits for it instead of
    // racing the scheduler — the expected arguments are asserted in full.
    await waitFor(() =>
      expect(setDataMock).toHaveBeenCalledWith([
        {
          time: Math.floor(Date.parse('2026-09-01T00:00:00Z') / 1000),
          open: 78563,
          high: 78854.2,
          low: 78562.9,
          close: 78613.7,
        },
        {
          time: Math.floor(Date.parse('2026-09-01T01:00:00Z') / 1000),
          open: 78614.4,
          high: 78772.6,
          low: 78364.2,
          close: 78382.1,
        },
      ]),
    );

    // The table prints the stored strings unchanged: no rounding, and a
    // value that was converted to a number for the chart would print as
    // `78563` instead of `78563.0`.
    const table = within(panel).getByRole('table');
    const cells = within(table)
      .getAllByRole('cell')
      .map((cell) => cell.textContent);
    expect(cells).toContain('78563.0');
    expect(cells).toContain('30.04552452');
    expect(cells).not.toContain('78563');

    // has_more is reported out loud rather than implied complete.
    expect(within(panel).getByText(/one page of the series/)).toBeTruthy();

    // The scroll box below the fold is keyboard-reachable and named, so a
    // keyboard-only operator can read every row (axe
    // `scrollable-region-focusable`).
    const scroller = within(panel).getByRole('region', {
      name: 'Stored bars table, scrollable',
    });
    expect(scroller.getAttribute('tabindex')).toBe('0');
  });

  it('shows ERROR with the exact failure when the API answers unusably', async () => {
    const message = 'API responded with 503 for /api/v1/datasets/kraken.xbtusd.1h/bars';
    const client = clientWith({
      getDatasetBars: () => Promise.reject(new ApiClientError('http', message, { status: 503 })),
    });

    render(<DatasetBars name="kraken.xbtusd.1h" client={client} />);

    expect((await screen.findByText('ERROR')).textContent).toBe('ERROR');
    expect(screen.getByText(message)).toBeTruthy();
    expect(screen.queryByRole('figure')).toBeNull();
    expect(screen.queryByText('CONNECTED')).toBeNull();
  });

  it('shows DISCONNECTED when the API cannot be reached', async () => {
    const message =
      'Cannot reach the API at http://127.0.0.1:8000: it is not running, the address is ' +
      'wrong, or the browser refused the response (CORS allow-list).';
    const client = clientWith({
      getDatasetBars: () => Promise.reject(new ApiClientError('network', message)),
    });

    render(<DatasetBars name="kraken.xbtusd.1h" client={client} />);

    expect((await screen.findByText('DISCONNECTED')).textContent).toBe('DISCONNECTED');
    expect(screen.getByText(message)).toBeTruthy();
    expect(screen.queryByRole('figure')).toBeNull();
  });

  it('reports the end of the window and shows a missing volume as a dash', async () => {
    const tail: DatasetBarsResponse = {
      ...BARS,
      bars: BARS.bars.slice(0, 1).map((bar) => ({ ...bar, volume: null })),
      returned: 1,
      has_more: false,
      next_cursor: null,
    };
    const client = clientWith({ getDatasetBars: () => Promise.resolve(tail) });

    render(<DatasetBars name="kraken.xbtusd.1h" client={client} />);

    await screen.findByText('1 bar(s) in this window.');

    expect(screen.getByText('The API reports no further bars for this window.')).toBeTruthy();
    // Null volume is a dash, never zero.
    expect(screen.getByText('—')).toBeTruthy();
    expect(screen.queryByText('0')).toBeNull();
    expect(within(screen.getByRole('table')).getAllByRole('cell')).toHaveLength(6);
  });
});
