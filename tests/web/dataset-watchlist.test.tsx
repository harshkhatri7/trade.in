/**
 * @vitest-environment jsdom
 *
 * The watchlist panel must reflect exactly the state it is given: real
 * directory metadata for followed datasets, a visible mark for a followed
 * name the directory no longer carries, `—` for fields that were never
 * recorded (never `0`), and the app-wide request-state wording. The names
 * live in the parent, so this component is pure presentation and every
 * assertion below drives it through explicit props. Payloads are the shared
 * Python/TypeScript fixture: real recorded metadata.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';

import type { DatasetListResponse } from '@harsh-quant-os/types';

import { DatasetWatchlist } from '../../apps/web/src/components/dataset-watchlist';
import fixture from '../contracts/datasets.json';

const SUMMARIES = (fixture.dataset_list as DatasetListResponse).datasets;
const FULL_VERSION = '0f27a08bfb355c898c0b8948da590c50dc612371599e34675f56c72ea8393883';

afterEach(() => cleanup());

describe('<DatasetWatchlist />', () => {
  it('waits with the directory instead of claiming a state it did not earn', () => {
    render(
      <DatasetWatchlist
        summaries={[]}
        listState="loading"
        names={['kraken.xbtusd.1h']}
        onToggle={vi.fn()}
        selected={null}
        onSelect={vi.fn()}
      />,
    );

    const panel = screen.getByRole('region', { name: 'Watchlist' });
    expect(panel.getAttribute('data-state')).toBe('loading');
    expect(within(panel).getByText('LOADING')).toBeTruthy();
    expect(within(panel).getByText(/Waiting for the directory/)).toBeTruthy();
    // No rows and no metadata may be rendered while nothing is known.
    expect(within(panel).queryByText('kraken.xbtusd.1h')).toBeNull();
  });

  it('says plainly when the directory failed, without pretending it is connected', () => {
    render(
      <DatasetWatchlist
        summaries={[]}
        listState="unavailable"
        names={['kraken.xbtusd.1h']}
        onToggle={vi.fn()}
        selected={null}
        onSelect={vi.fn()}
      />,
    );

    const panel = screen.getByRole('region', { name: 'Watchlist' });
    expect(panel.getAttribute('data-state')).toBe('unavailable');
    expect(within(panel).getByText('DISCONNECTED')).toBeTruthy();
    expect(within(panel).getByText(/could not be reached/)).toBeTruthy();
    expect(within(panel).queryByText('kraken.xbtusd.1h')).toBeNull();
  });

  it('offers the empty state when nothing is followed', () => {
    render(
      <DatasetWatchlist
        summaries={SUMMARIES}
        listState="connected"
        names={[]}
        onToggle={vi.fn()}
        selected={null}
        onSelect={vi.fn()}
      />,
    );

    const panel = screen.getByRole('region', { name: 'Watchlist' });
    expect(panel.getAttribute('data-state')).toBe('connected');
    expect(within(panel).getByText(/No datasets followed yet/)).toBeTruthy();
    expect(within(panel).queryByRole('button')).toBeNull();
  });

  it('renders followed datasets with exact stored metadata and the artefact prefix', () => {
    render(
      <DatasetWatchlist
        summaries={SUMMARIES}
        listState="connected"
        names={['kraken.xbtusd.1h']}
        onToggle={vi.fn()}
        selected={null}
        onSelect={vi.fn()}
      />,
    );

    const panel = screen.getByRole('region', { name: 'Watchlist' });
    expect(within(panel).getByText('kraken.xbtusd.1h')).toBeTruthy();
    expect(within(panel).getByText('XBTUSD')).toBeTruthy();
    expect(within(panel).getByText('1h')).toBeTruthy();
    expect(within(panel).getByText('649 rows')).toBeTruthy();
    expect(within(panel).getByText('0f27a08b…')).toBeTruthy();
    // The full version is in the row's title so it can still be named exactly.
    expect(within(panel).getByText('0f27a08b…').getAttribute('title')).toBe(FULL_VERSION);
    // Never an invented quality or price: the panel shows metadata only.
    expect(within(panel).queryByText('suspect')).toBeNull();
  });

  it('renders unrecorded fields as a dash, never as zero', () => {
    render(
      <DatasetWatchlist
        summaries={SUMMARIES}
        listState="connected"
        names={['example.pending.1d']}
        onToggle={vi.fn()}
        selected={null}
        onSelect={vi.fn()}
      />,
    );

    const panel = screen.getByRole('region', { name: 'Watchlist' });
    expect(within(panel).getByText('example.pending.1d')).toBeTruthy();
    // row_count, instrument, timeframe and version are all null in the
    // fixture: none of them may become 0 or an empty claim.
    expect(within(panel).getByText('— rows')).toBeTruthy();
    expect(within(panel).getAllByText('—').length).toBeGreaterThanOrEqual(3);
    expect(within(panel).queryByText('0 rows')).toBeNull();
  });

  it('keeps a followed name that left the directory, marked and removable', () => {
    const onToggle = vi.fn();
    render(
      <DatasetWatchlist
        summaries={SUMMARIES}
        listState="connected"
        names={['kraken.xbtusd.1h', 'retired.dataset.5m']}
        onToggle={onToggle}
        selected={null}
        onSelect={vi.fn()}
      />,
    );

    const panel = screen.getByRole('region', { name: 'Watchlist' });
    expect(within(panel).getByText('(not in directory)')).toBeTruthy();

    // Removal goes through the parent's toggle for either kind of row.
    const removeMissing = within(panel).getByRole('button', {
      name: 'Remove retired.dataset.5m from the watchlist',
    });
    fireEvent.click(removeMissing);
    expect(onToggle).toHaveBeenCalledWith('retired.dataset.5m');

    const removePresent = within(panel).getByRole('button', {
      name: 'Remove kraken.xbtusd.1h from the watchlist',
    });
    fireEvent.click(removePresent);
    expect(onToggle).toHaveBeenCalledWith('kraken.xbtusd.1h');
  });

  it('opens the detail panel through the same handler as a directory row', () => {
    const onSelect = vi.fn();
    render(
      <DatasetWatchlist
        summaries={SUMMARIES}
        listState="connected"
        names={['kraken.xbtusd.1h']}
        onToggle={vi.fn()}
        selected="kraken.xbtusd.1h"
        onSelect={onSelect}
      />,
    );

    const open = screen.getByRole('button', { name: 'Open kraken.xbtusd.1h' });
    // The open dataset is marked on the row itself.
    expect(open.getAttribute('aria-current')).toBe('true');
    fireEvent.click(open);
    expect(onSelect).toHaveBeenCalledWith('kraken.xbtusd.1h');
  });
});
