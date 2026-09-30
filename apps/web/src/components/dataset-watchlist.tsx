'use client';

/**
 * Watchlist panel: the datasets this workspace follows.
 *
 * The names themselves live in the parent (`useWatchlist` in the dataset
 * browser), so this panel and the directory's Follow buttons always agree —
 * one state, one source of truth, no cross-component localStorage guessing.
 *
 * - A followed name that is still in the directory renders with its
 *   metadata; clicking the name opens the same detail panel as a
 *   directory row (`onSelect`).
 * - A followed name that has left the directory is kept, marked
 *   "(not in directory)", and can still be removed. Nothing the operator
 *   followed disappears silently.
 * - A field the API could not fill renders as `—`, never `0`: "not
 *   counted" and "zero rows" are different facts.
 *
 * The directory's request state is passed through and rendered with the
 * app-wide wording and tones (`request-state.ts`), so this panel never
 * claims CONNECTED while the directory is loading or failed.
 */
import type { ReactElement } from 'react';

import type { DatasetSummary } from '@harsh-quant-os/types';

import { REQUEST_STATE_LABELS, REQUEST_STATE_TONES } from '../features/common/request-state';
import type { RequestStateKind } from '../features/common/request-state';

/** What an unfilled field renders as. Deliberately not `0`. */
const UNKNOWN = '—';

/** The directory is never `idle`: it starts in `loading`. */
export type WatchlistListState = Exclude<RequestStateKind, 'idle'>;

export interface DatasetWatchlistProps {
  /** Current directory, so followed rows can show real metadata. */
  readonly summaries: DatasetSummary[];
  /** Directory request state (`loading` | `connected` | `error` | `unavailable`). */
  readonly listState: WatchlistListState;
  /** Followed dataset names, in insertion order. */
  readonly names: readonly string[];
  /** Adds or removes one name (shared with the directory's Follow buttons). */
  readonly onToggle: (name: string) => void;
  /** Dataset whose detail panel is open, highlighted here. */
  readonly selected: string | null;
  /** Opens the detail panel, same handler as a directory row. */
  readonly onSelect: (name: string) => void;
}

function stateNote(listState: WatchlistListState): string {
  if (listState === 'error') {
    return 'The directory request failed; following is paused until it answers.';
  }
  if (listState === 'unavailable') {
    return 'The API could not be reached; following is paused until it answers.';
  }
  if (listState === 'loading') {
    return 'Waiting for the directory to answer…';
  }
  return '';
}

export function DatasetWatchlist({
  summaries,
  listState,
  names,
  onToggle,
  selected,
  onSelect,
}: DatasetWatchlistProps) {
  // Followed datasets that are still in the directory, in insertion order.
  const present = names
    .map((name) => summaries.find((s) => s.name === name))
    .filter((s): s is DatasetSummary => s !== undefined);
  // Followed names the directory no longer carries: kept, marked, removable.
  const missing = names.filter((name) => !summaries.some((s) => s.name === name));

  const removeButton = (name: string) => (
    <button
      type="button"
      onClick={() => onToggle(name)}
      className="ml-auto rounded-full border border-line px-2 py-0.5 text-xs uppercase tracking-[0.12em] text-muted hover:text-ink"
    >
      Remove <span className="sr-only">{name} from the watchlist</span>
    </button>
  );

  const renderPresent = (s: DatasetSummary) => (
    <li
      key={s.name}
      className="flex flex-wrap items-baseline gap-2 border-b border-line py-2 text-sm last:border-b-0"
    >
      <button
        type="button"
        onClick={() => onSelect(s.name)}
        aria-label={`Open ${s.name}`}
        aria-current={selected === s.name}
        className="text-left font-mono text-ink underline decoration-line underline-offset-4 hover:decoration-accent focus-visible:decoration-accent"
      >
        {s.name}
      </button>
      <span className="capitalize text-muted">{s.instrument ?? UNKNOWN}</span>
      <span className="capitalize text-muted">{s.timeframe ?? UNKNOWN}</span>
      <span className="font-mono text-xs tabular-nums text-muted">
        {s.row_count === null ? UNKNOWN : s.row_count} rows
      </span>
      <span className="truncate font-mono text-xs text-muted" title={s.version ?? undefined}>
        {s.version === null ? UNKNOWN : `${s.version.slice(0, 8)}…`}
      </span>
      {removeButton(s.name)}
    </li>
  );

  const renderMissing = (name: string) => (
    <li
      key={name}
      className="flex flex-wrap items-baseline gap-2 border-b border-line py-2 text-sm last:border-b-0"
    >
      <span className="font-mono text-ink">{name}</span>
      <span className="text-xs text-muted">(not in directory)</span>
      {removeButton(name)}
    </li>
  );

  let section: ReactElement;

  if (listState === 'loading' || listState === 'error' || listState === 'unavailable') {
    section = (
      <p className="mt-4 text-sm text-muted" role="note">
        {stateNote(listState)}
      </p>
    );
  } else if (names.length === 0) {
    section = (
      <p className="mt-4 text-sm text-muted">
        No datasets followed yet.
        <br />
        Use “Follow” on a directory row to keep one here.
      </p>
    );
  } else {
    section = (
      <ul className="mt-4">
        {present.map(renderPresent)}
        {missing.map(renderMissing)}
      </ul>
    );
  }

  return (
    <section
      aria-labelledby="watchlist-heading"
      data-state={listState}
      className="rounded-lg border border-line bg-raised p-4 sm:p-6"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="watchlist-heading" className="text-lg font-semibold tracking-tight">
          Watchlist
        </h2>
        <p
          role="status"
          className={
            'font-mono text-sm font-semibold tracking-wide ' + REQUEST_STATE_TONES[listState]
          }
        >
          {REQUEST_STATE_LABELS[listState]}
        </p>
      </div>
      <p className="mt-1 text-xs text-muted">
        Followed datasets, stored in this browser. {names.length} followed.
      </p>
      {section}
    </section>
  );
}
