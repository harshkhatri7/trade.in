/**
 * @vitest-environment jsdom
 *
 * The multi-timeframe panel must only offer what exists: one chip per
 * canonical timeframe, in canonical order, with a working button exactly
 * where a stored dataset matches — and the click must open that dataset by
 * its real name, not a constructed identifier. Datasets that cannot be
 * placed on the grid are named in the footnote instead of being dropped.
 * The directory payload is the shared Python/TypeScript fixture: real
 * recorded metadata; the only constructed value is a second timeframe for
 * the same instrument, built by copying that real record, so grouping has
 * more than one timeframe to place.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';

import { TIMEFRAMES } from '@harsh-quant-os/types';
import type { DatasetListResponse, DatasetSummary } from '@harsh-quant-os/types';

import { DatasetMultiTimeframe } from '../../apps/web/src/components/dataset-multi-timeframe';
import fixture from '../contracts/datasets.json';

const SUMMARIES = (fixture.dataset_list as DatasetListResponse).datasets;

/** The real XBTUSD record plus a copy of it carrying a second timeframe. */
const XBTUSD_SUMMARY = SUMMARIES[0]!;
const XBTUSD_GROUP: DatasetSummary[] = [
  XBTUSD_SUMMARY,
  { ...XBTUSD_SUMMARY, name: 'kraken.xbtusd.1d', timeframe: '1d' },
];

afterEach(() => cleanup());

function groupChips(): (string | null)[] {
  const heading = screen.getByRole('heading', { name: 'XBTUSD' });
  const row = heading.parentElement!.querySelector('div.flex');
  return Array.from(row!.children).map((chip) => chip.textContent?.split(' (')[0] ?? null);
}

describe('<DatasetMultiTimeframe />', () => {
  it('waits with the directory instead of claiming a state it did not earn', () => {
    render(<DatasetMultiTimeframe summaries={SUMMARIES} listState="loading" onSelect={vi.fn()} />);

    const panel = screen.getByRole('region', { name: 'Multi-timeframe views' });
    expect(panel.getAttribute('data-state')).toBe('loading');
    expect(within(panel).getByText('LOADING')).toBeTruthy();
    expect(within(panel).getByText(/Waiting for the directory/)).toBeTruthy();
    expect(within(panel).queryByRole('button')).toBeNull();
    expect(within(panel).queryByRole('heading', { name: 'XBTUSD' })).toBeNull();
  });

  it('says plainly when the directory failed', () => {
    render(<DatasetMultiTimeframe summaries={SUMMARIES} listState="error" onSelect={vi.fn()} />);

    const panel = screen.getByRole('region', { name: 'Multi-timeframe views' });
    expect(panel.getAttribute('data-state')).toBe('error');
    expect(within(panel).getByText('ERROR')).toBeTruthy();
    expect(within(panel).getByText('The directory request failed.')).toBeTruthy();
  });

  it('renders every canonical timeframe once, in canonical order', () => {
    render(
      <DatasetMultiTimeframe summaries={XBTUSD_GROUP} listState="connected" onSelect={vi.fn()} />,
    );

    expect(groupChips()).toEqual([...TIMEFRAMES]);
  });

  it('offers a button only where a dataset is stored, and opens it by its real name', () => {
    const onSelect = vi.fn();
    render(
      <DatasetMultiTimeframe summaries={XBTUSD_GROUP} listState="connected" onSelect={onSelect} />,
    );

    const panel = screen.getByRole('region', { name: 'Multi-timeframe views' });

    // Both stored timeframes are buttons that open their dataset.
    const hour = within(panel).getByRole('button', { name: 'View 1h of XBTUSD' });
    fireEvent.click(hour);
    expect(onSelect).toHaveBeenCalledWith('kraken.xbtusd.1h');

    const day = within(panel).getByRole('button', { name: 'View 1d of XBTUSD' });
    fireEvent.click(day);
    expect(onSelect).toHaveBeenCalledWith('kraken.xbtusd.1d');

    // Every other timeframe is shown but is not a button: there is nothing
    // behind it, and the panel must not pretend otherwise.
    expect(onSelect).toHaveBeenCalledTimes(2);
    expect(within(panel).queryByRole('button', { name: 'View 5m of XBTUSD' })).toBeNull();
    expect(within(panel).getAllByText('(not stored)').length).toBe(TIMEFRAMES.length - 2);
  });

  it('names the datasets it cannot group instead of dropping them', () => {
    render(
      <DatasetMultiTimeframe summaries={SUMMARIES} listState="connected" onSelect={vi.fn()} />,
    );

    const panel = screen.getByRole('region', { name: 'Multi-timeframe views' });
    // The fixture's pending dataset has no instrument and no timeframe.
    expect(within(panel).getByText(/example\.pending\.1d/)).toBeTruthy();
    expect(within(panel).getByText(/cannot be grouped/)).toBeTruthy();
    // Only XBTUSD can be grouped from this fixture.
    expect(within(panel).getByRole('heading', { name: 'XBTUSD' })).toBeTruthy();
  });

  it('says so plainly when nothing can be grouped yet', () => {
    render(<DatasetMultiTimeframe summaries={[]} listState="connected" onSelect={vi.fn()} />);

    const panel = screen.getByRole('region', { name: 'Multi-timeframe views' });
    expect(within(panel).getByText(/No dataset with a recorded instrument/)).toBeTruthy();
    // The section title is the only heading; no instrument group appeared.
    expect(within(panel).queryByRole('heading', { level: 3 })).toBeNull();
  });
});
