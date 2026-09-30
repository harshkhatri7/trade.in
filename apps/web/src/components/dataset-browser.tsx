'use client';

/**
 * Dataset browser: what has been ingested, what validation recorded about
 * it, and the artefact version every figure was read from.
 *
 * Every value on screen comes from a validated payload — the directory from
 * `GET /api/v1/datasets`, the provenance panel from
 * `GET /api/v1/datasets/{name}`, the bars from
 * `GET /api/v1/datasets/{name}/bars`. A field the API could not fill arrives
 * as `null` and renders as `—`; it is never rendered as `0`, because "not
 * counted" and "zero rows" are different facts (the same rule the Python
 * contract enforces). Quality colours are never the only signal: the status
 * word is always rendered next to them.
 *
 * The directory shows a shortened version because it is an index; the
 * detail panel always shows the full SHA-256, so a figure can be named
 * exactly and the artefact identified without hovering anything.
 */
import { useState } from 'react';

import type {
  DataQualityStatus,
  DatasetDetailResponse,
  DatasetProvenanceEntry,
} from '@harsh-quant-os/types';

import type { ApiClient } from '../api-client';
import { defaultApiClient } from '../api-client';
import { REQUEST_STATE_LABELS, REQUEST_STATE_TONES } from '../features/common/request-state';
import { useDatasetDetail, useDatasetList } from '../features/datasets/use-datasets';
import type { DatasetDetailState, DatasetListState } from '../features/datasets/use-datasets';
import { useWatchlist } from '../features/datasets/use-watchlist';
import { DatasetBars } from './dataset-bars';
import { DatasetMultiTimeframe } from './dataset-multi-timeframe';
import { DatasetWatchlist } from './dataset-watchlist';

export interface DatasetBrowserProps {
  /** Injected in tests; production uses the configured default client. */
  readonly client?: ApiClient;
}

/** What an unfilled field renders as. Deliberately not `0`. */
const UNKNOWN = '—';

const QUALITY_TONES: Record<DataQualityStatus, string> = {
  valid: 'text-accent',
  suspect: 'text-warning',
  invalid: 'text-critical',
  pending: 'text-muted',
  unknown: 'text-muted',
};

function shown(value: string | number | null): string {
  return value === null ? UNKNOWN : String(value);
}

/** Shortened for the directory index only; the detail panel shows the full value. */
function shortVersion(version: string): string {
  return `${version.slice(0, 12)}…`;
}

/**
 * Display step for the directory: whole seconds, UTC.
 *
 * The list is an index — it shows the same instant without its
 * microseconds, which keeps the table inside the viewport. The exact
 * recorded value is rendered in full in the detail panel, and `title`
 * carries it on the cell itself. An instant that is not the ISO shape this
 * API emits is returned unchanged, so an unexpected format reaches the
 * screen as received rather than mangled.
 */
function shortInstant(iso: string): string {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/.exec(iso);
  return match === null ? iso : `${match[1]} ${match[2]}Z`;
}

function listNote(list: DatasetListState, count: number): string {
  if (list.kind === 'error' || list.kind === 'unavailable') {
    // The underlying failure exactly as the client reported it: a network
    // failure, an HTTP status or a contract violation is never softened.
    return list.message;
  }
  if (list.kind === 'loading') {
    return 'Waiting for the API to answer…';
  }
  if (count === 0) {
    return 'No datasets are registered in this workspace yet.';
  }
  return `${count} dataset(s) listed.`;
}

function detailNote(detail: DatasetDetailState): string {
  if (detail.kind === 'error' || detail.kind === 'unavailable') {
    return detail.message;
  }
  if (detail.kind === 'connected') {
    return `${detail.value.provenance.length} acquisition record(s), newest first.`;
  }
  return 'Waiting for the API to answer…';
}

function QualityBadge({ status }: { readonly status: DataQualityStatus }) {
  return (
    <span className={'font-mono text-xs font-semibold uppercase ' + QUALITY_TONES[status]}>
      {status}
    </span>
  );
}

function DetailRow({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line py-3 last:border-b-0">
      <dt className="text-xs uppercase tracking-[0.18em] text-muted">{label}</dt>
      <dd className="break-all text-right font-mono text-sm text-ink">{value}</dd>
    </div>
  );
}

/** Checksums are shown in full: a shortened one cannot be verified against anything. */
function ProvenanceTable({ entries }: { readonly entries: DatasetProvenanceEntry[] }) {
  if (entries.length === 0) {
    return <p className="mt-3 text-sm text-muted">No acquisition has been recorded.</p>;
  }

  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">Append-only acquisition history, newest first</caption>
        <thead>
          <tr className="border-b border-line text-left text-xs uppercase tracking-[0.16em] text-muted">
            <th scope="col" className="py-2 pr-4 font-medium">
              Acquired (UTC)
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              Source
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              Rows
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              Checksum (SHA-256)
            </th>
            <th scope="col" className="py-2 font-medium">
              Notes
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr
              key={`${entry.acquired_at}|${entry.source}|${entry.notes ?? ''}`}
              className="border-b border-line align-top last:border-b-0"
            >
              <td className="py-3 pr-4 font-mono text-xs">{entry.acquired_at}</td>
              <td className="break-all py-3 pr-4 font-mono text-xs">{entry.source}</td>
              <td className="py-3 pr-4 text-right font-mono tabular-nums">
                {shown(entry.row_count)}
              </td>
              <td className="break-all py-3 pr-4 font-mono text-xs">
                {shown(entry.checksum_sha256)}
              </td>
              <td className="py-3 text-muted">{shown(entry.notes)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DetailPanel({
  detail,
  client,
}: {
  readonly detail: DatasetDetailResponse;
  readonly client: ApiClient;
}) {
  const dataset = detail.dataset;

  return (
    <div className="mt-6 space-y-8">
      <dl>
        <DetailRow label="Version (SHA-256 of the artefact)" value={shown(dataset.version)} />
        <DetailRow label="Instrument" value={shown(dataset.instrument)} />
        <DetailRow label="Timeframe" value={shown(dataset.timeframe)} />
        <DetailRow label="Quality status" value={dataset.quality_status} />
        <DetailRow label="Rows" value={shown(dataset.row_count)} />
        <DetailRow label="Source" value={shown(dataset.source)} />
        <DetailRow label="Acquired (UTC)" value={shown(dataset.acquired_at)} />
        <DetailRow label="Updated (UTC)" value={dataset.updated_at} />
        <DetailRow label="Storage path" value={shown(dataset.storage_path)} />
      </dl>

      <DatasetBars name={dataset.name} client={client} />

      <div>
        <h3 className="text-sm font-semibold uppercase tracking-[0.18em]">Acquisition history</h3>
        <p className="mt-1 text-xs text-muted">
          Append-only: a correction appears as another entry, and nothing already recorded is
          rewritten.
        </p>
        <ProvenanceTable entries={detail.provenance} />
      </div>

      <p className="text-xs text-muted">
        {UNKNOWN} means the value was not recorded — never zero. The version above names the
        artefact every figure on this page was read from.
      </p>
    </div>
  );
}

export function DatasetBrowser({ client = defaultApiClient }: DatasetBrowserProps) {
  const list = useDatasetList(client);
  const [selected, setSelected] = useState<string | null>(null);
  const detail = useDatasetDetail(client, selected);
  // One watchlist for the whole page: the directory's Follow buttons and the
  // watchlist panel below read and write the same persisted state.
  const [watchlist, toggleWatchlist] = useWatchlist();
  const datasets = list.kind === 'connected' ? list.response.datasets : [];

  return (
    <div className="space-y-8">
      <section
        aria-labelledby="dataset-directory-heading"
        data-state={list.kind}
        className="rounded-lg border border-line bg-raised p-6 sm:p-8"
      >
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="dataset-directory-heading" className="text-lg font-semibold tracking-tight">
            Dataset directory
          </h2>
          <p className="text-xs uppercase tracking-[0.18em] text-muted">Live API response</p>
        </div>

        <p className="mt-4 flex flex-wrap items-baseline gap-3 text-sm">
          <span
            role="status"
            className={
              'font-mono text-sm font-semibold tracking-wide ' + REQUEST_STATE_TONES[list.kind]
            }
          >
            {REQUEST_STATE_LABELS[list.kind]}
          </span>
          <span className="text-muted">{listNote(list, datasets.length)}</span>
        </p>

        {list.kind === 'connected' &&
          (datasets.length === 0 ? (
            <p className="mt-6 max-w-2xl text-sm text-muted">
              Nothing has been ingested yet. A dataset appears here once{' '}
              <code className="font-mono text-ink">hqos data ingest</code> has validated it and
              recorded where it came from.
            </p>
          ) : (
            <div className="mt-6 space-y-4">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <caption className="sr-only">
                    Stored datasets with quality status, row count and artefact version
                  </caption>
                  <thead>
                    <tr className="border-b border-line text-left text-xs uppercase tracking-[0.16em] text-muted">
                      <th scope="col" className="py-2 pr-4 font-medium">
                        Dataset
                      </th>
                      <th scope="col" className="py-2 pr-4 font-medium">
                        Instrument
                      </th>
                      <th scope="col" className="py-2 pr-4 font-medium">
                        Timeframe
                      </th>
                      <th scope="col" className="py-2 pr-4 font-medium">
                        Quality
                      </th>
                      <th scope="col" className="py-2 pr-4 text-right font-medium">
                        Rows
                      </th>
                      <th scope="col" className="py-2 pr-4 font-medium">
                        Version
                      </th>
                      <th scope="col" className="py-2 font-medium">
                        Acquired (UTC)
                      </th>
                      <th scope="col" className="py-2 font-medium">
                        Watchlist
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {datasets.map((dataset) => (
                      <tr
                        key={dataset.name}
                        className="border-b border-line align-top last:border-b-0"
                      >
                        <th scope="row" className="py-3 pr-4 text-left font-medium">
                          <button
                            type="button"
                            onClick={() => setSelected(dataset.name)}
                            aria-pressed={selected === dataset.name}
                            className="text-left font-mono underline decoration-line underline-offset-4 hover:decoration-accent focus-visible:decoration-accent"
                          >
                            {dataset.name}
                          </button>
                        </th>
                        <td className="py-3 pr-4 font-mono">{shown(dataset.instrument)}</td>
                        <td className="py-3 pr-4 font-mono">{shown(dataset.timeframe)}</td>
                        <td className="py-3 pr-4">
                          <QualityBadge status={dataset.quality_status} />
                        </td>
                        <td className="py-3 pr-4 text-right font-mono tabular-nums">
                          {shown(dataset.row_count)}
                        </td>
                        <td className="py-3 pr-4 font-mono text-xs">
                          {dataset.version === null ? (
                            UNKNOWN
                          ) : (
                            <span title={dataset.version}>{shortVersion(dataset.version)}</span>
                          )}
                        </td>
                        <td className="py-3 font-mono text-xs">
                          {dataset.acquired_at === null ? (
                            UNKNOWN
                          ) : (
                            <span title={dataset.acquired_at}>
                              {shortInstant(dataset.acquired_at)}
                            </span>
                          )}
                        </td>
                        <td className="py-3">
                          <button
                            type="button"
                            onClick={() => toggleWatchlist(dataset.name)}
                            aria-pressed={watchlist.includes(dataset.name)}
                            aria-label={`Follow ${dataset.name}`}
                            className="rounded-full border border-line px-2 py-0.5 text-xs uppercase tracking-[0.12em] text-muted hover:text-ink"
                          >
                            Follow
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-muted">
                {UNKNOWN} means the value was not recorded — never zero. Select a dataset to see its
                full version, storage path and append-only acquisition history.
              </p>
            </div>
          ))}
      </section>

      {/* Watchlist and multi-timeframe share the directory's request state:
          neither may claim CONNECTED while the directory has not answered. */}
      <div className="grid gap-8 lg:grid-cols-2">
        <DatasetWatchlist
          summaries={datasets}
          listState={list.kind}
          names={watchlist}
          onToggle={toggleWatchlist}
          selected={selected}
          onSelect={setSelected}
        />
        <DatasetMultiTimeframe summaries={datasets} listState={list.kind} onSelect={setSelected} />
      </div>

      {selected !== null && (
        <section
          aria-labelledby="dataset-detail-heading"
          data-state={detail.kind}
          className="rounded-lg border border-line bg-raised p-6 sm:p-8"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h2
              id="dataset-detail-heading"
              className="break-all font-mono text-lg font-semibold tracking-tight"
            >
              {selected}
            </h2>
            <button
              type="button"
              onClick={() => setSelected(null)}
              className="rounded-full border border-line px-3 py-1 text-xs uppercase tracking-[0.16em] text-muted hover:text-ink"
            >
              Close
            </button>
          </div>

          <p className="mt-4 flex flex-wrap items-baseline gap-3 text-sm">
            <span
              role="status"
              className={
                'font-mono text-sm font-semibold tracking-wide ' + REQUEST_STATE_TONES[detail.kind]
              }
            >
              {REQUEST_STATE_LABELS[detail.kind]}
            </span>
            <span className="text-muted">{detailNote(detail)}</span>
          </p>

          {detail.kind === 'connected' && <DetailPanel detail={detail.value} client={client} />}
        </section>
      )}
    </div>
  );
}
