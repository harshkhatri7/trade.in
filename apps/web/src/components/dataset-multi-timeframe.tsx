'use client';

/**
 * Multi-timeframe view: which timeframes exist for each instrument.
 *
 * The directory is grouped by instrument (first-appearance order) and each
 * group renders the canonical timeframe row. A timeframe button is enabled
 * only when a dataset actually exists for that instrument+timeframe — the
 * button then opens exactly that dataset via `onSelect(name)`, the same
 * handler a directory row uses. A timeframe with no stored dataset is
 * rendered as a dashed chip (not a button, not clickable): the grid shows
 * what is missing without pretending it can be opened.
 *
 * Datasets with no instrument recorded cannot be grouped; they are
 * reported in a footnote rather than silently dropped.
 *
 * Grouping is a plain memoised computation at the top level — no hooks
 * inside render loops, so the hook order is the same on every render.
 * Request state is rendered with the app-wide wording and tones
 * (`request-state.ts`).
 *
 * Chips are flat and small — this grid is the densest surface in the app,
 * and giving each of them its own blur would multiply the compositing cost
 * for no visual gain at 8px.
 */
import { useMemo } from 'react';

import { TIMEFRAMES } from '@harsh-quant-os/types';
import type { DatasetSummary } from '@harsh-quant-os/types';

import { REQUEST_STATE_LABELS, REQUEST_STATE_TONES } from '../features/common/request-state';
import type { RequestStateKind } from '../features/common/request-state';

/** The directory is never `idle`: it starts in `loading`. */
export type MultiTimeframeListState = Exclude<RequestStateKind, 'idle'>;

export interface DatasetMultiTimeframeProps {
  /** Current directory, grouped by instrument. */
  readonly summaries: DatasetSummary[];
  /** Directory request state (`loading` | `connected` | `error` | `unavailable`). */
  readonly listState: MultiTimeframeListState;
  /** Opens the detail panel for the chosen dataset, same handler as a row. */
  readonly onSelect: (name: string) => void;
}

function stateNote(listState: MultiTimeframeListState): string {
  if (listState === 'error') {
    return 'The directory request failed.';
  }
  if (listState === 'unavailable') {
    return 'The API could not be reached.';
  }
  return 'Waiting for the directory to answer…';
}

export function DatasetMultiTimeframe({
  summaries,
  listState,
  onSelect,
}: DatasetMultiTimeframeProps) {
  // Group by instrument (non-null). Preserve first-appearance order.
  const groups = useMemo(() => {
    const map = new Map<string, DatasetSummary[]>();
    const order: string[] = [];
    for (const s of summaries) {
      if (s.instrument === null) continue;
      const bucket = map.get(s.instrument);
      if (bucket === undefined) {
        map.set(s.instrument, [s]);
        order.push(s.instrument);
      } else {
        bucket.push(s);
      }
    }
    return { map, order };
  }, [summaries]);

  // Anything that cannot be placed on the grid: no instrument to group by
  // and/or no timeframe to place it under. Never silently dropped — each
  // one is named in the footnote below.
  const ungrouped = summaries.filter((s) => s.instrument === null || s.timeframe === null);

  const renderGroup = (instrument: string, entries: DatasetSummary[]) => {
    // Datasets in this group that carry a timeframe (null timeframe cannot
    // be placed on the canonical row and is reported in the footnote).
    const timed = entries.filter((e) => e.timeframe !== null);
    if (timed.length === 0) return null;

    return (
      <div key={instrument} className="space-y-3">
        <h3 className="eyebrow">{instrument}</h3>
        <div className="flex flex-wrap gap-2">
          {TIMEFRAMES.map((tf) => {
            const match = timed.find((e) => e.timeframe === tf);
            if (match === undefined) {
              return (
                <span
                  key={tf}
                  className="inline-flex min-h-8 cursor-default items-center rounded-md border border-dashed border-white/10 px-3 text-xs font-medium text-muted"
                >
                  {tf}
                  <span className="sr-only"> (not stored)</span>
                </span>
              );
            }
            return (
              <button
                key={tf}
                type="button"
                onClick={() => onSelect(match.name)}
                aria-label={`View ${tf} of ${instrument}`}
                className="pill pill-accent"
              >
                {tf}
              </button>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <section aria-labelledby="multi-timeframe-heading" data-state={listState} className="panel">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="multi-timeframe-heading" className="panel-title">
          Multi-timeframe views
        </h2>
        <p role="status" className={'state-chip ' + REQUEST_STATE_TONES[listState]}>
          {REQUEST_STATE_LABELS[listState]}
        </p>
      </div>

      {listState !== 'connected' ? (
        <p className="note mt-4" role="note">
          {stateNote(listState)}
        </p>
      ) : groups.order.length === 0 ? (
        <div className="panel-inset mt-4">
          <p className="text-sm text-muted">
            No dataset with a recorded instrument can be grouped into a multi-timeframe view yet.
          </p>
        </div>
      ) : (
        <div className="mt-4 space-y-5">
          {groups.order.map((inst) => renderGroup(inst, groups.map.get(inst)!))}
        </div>
      )}

      {listState === 'connected' && ungrouped.length > 0 && (
        <p className="note mt-4 text-xs">
          {ungrouped.length === 1 ? 'One dataset lacks' : `${ungrouped.length} datasets lack`} the
          instrument and/or timeframe needed to be placed on this grid (
          {ungrouped.map((s) => s.name).join(', ')}) and cannot be grouped into a multi-timeframe
          view.
        </p>
      )}
    </section>
  );
}
