'use client';

/**
 * Bars section of the dataset detail panel: a candlestick chart of the
 * stored bars plus a table of the same page of data.
 *
 * Chart and table read one payload, so what is drawn and what is printed
 * cannot disagree. Prices arrive as decimal strings; the table keeps them
 * verbatim, and converting them to numbers is a display step for the
 * chart's geometry, performed here and nowhere else. The dataset version
 * the payload carries is rendered above both — the figure names its
 * artefact, which is the Phase 4 exit criterion applied to this panel.
 *
 * A bar timestamp that does not parse can never reach this component:
 * `parseBarPoint` in the shared contract rejects it (`readTimestamp`
 * requires `Date.parse` to succeed) and the panel renders `error` instead
 * of a chart — no silently skipped point, no crash.
 *
 * The candles use the design tokens (accent up, critical down); the
 * bodies already differ by shape and the table restates every value as
 * text, so colour is never the only signal. jsdom has no canvas, so
 * component tests replace `lightweight-charts` with a stub and assert the
 * data handed to it rather than pixels; the rendered chart itself is
 * verified in a real browser.
 *
 * The chart is the one place where the library's own colours are written
 * as hex: `lightweight-charts` draws on a canvas and takes literal colour
 * strings, so the values are re-read from the design tokens on mount via
 * `getComputedStyle` — one token source, no second palette drifting in
 * parallel. The flat chart surface carries no `backdrop-filter`, so
 * redrawing during a pan costs no offscreen composite.
 */
import { useEffect, useMemo, useRef } from 'react';

import { CandlestickSeries, ColorType, createChart } from 'lightweight-charts';
import type { UTCTimestamp } from 'lightweight-charts';

import type { BarPoint, DatasetBarsResponse } from '@harsh-quant-os/types';

import type { ApiClient } from '../api-client';
import { defaultApiClient } from '../api-client';
import { REQUEST_STATE_LABELS, REQUEST_STATE_TONES } from '../features/common/request-state';
import { useDatasetBars } from '../features/datasets/use-datasets';
import type { DatasetBarsState } from '../features/datasets/use-datasets';

export interface DatasetBarsProps {
  /** Name of the selected dataset; the request starts with the selection. */
  readonly name: string;
  /** Injected in tests; production uses the configured default client. */
  readonly client?: ApiClient;
}

/** What an unfilled volume renders as in the table. Deliberately not `0`. */
const UNKNOWN = '—';

/**
 * Read one token out of the document's computed styles.
 *
 * Falls back to the token's literal value only when the stylesheet is not
 * resolvable (jsdom in tests): the fallback is the same hex the token
 * defines, so the chart and the UI cannot show different colours, and the
 * test path is never *different* data — only the same value read without a
 * layout engine.
 */
function token(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  try {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value === '' ? fallback : value;
  } catch {
    return fallback;
  }
}

function barsNote(state: DatasetBarsState): string {
  if (state.kind === 'error' || state.kind === 'unavailable') {
    // The failure exactly as the client reported it: a network failure,
    // an HTTP status or a contract violation is never softened.
    return state.message;
  }
  if (state.kind === 'connected') {
    return `${state.value.returned} bar(s) in this window.`;
  }
  return 'Waiting for the API to answer…';
}

function PriceChart({ bars, label }: { readonly bars: BarPoint[]; readonly label: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  // One conversion, memoised on the payload: the chart's `setData` effect
  // must not refire for an unrelated re-render of the panel.
  const points = useMemo(
    () =>
      bars.map((bar) => ({
        time: Math.floor(Date.parse(bar.timestamp) / 1000) as UTCTimestamp,
        open: Number(bar.open),
        high: Number(bar.high),
        low: Number(bar.low),
        close: Number(bar.close),
      })),
    [bars],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) {
      return undefined;
    }

    // Design tokens, read once at mount: the same `--color-*` values the
    // rest of the interface paints with.
    const inkMuted = token('--color-muted', '#9aa7b8');
    const line = token('--color-line', '#1f2632');
    const accent = token('--color-accent', '#7ee0b0');
    const critical = token('--color-critical', '#ff9494');

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: inkMuted,
      },
      grid: {
        vertLines: { color: line },
        horzLines: { color: line },
      },
      rightPriceScale: { borderColor: line },
      timeScale: { borderColor: line, timeVisible: true, secondsVisible: false },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: accent,
      downColor: critical,
      borderUpColor: accent,
      borderDownColor: critical,
      wickUpColor: accent,
      wickDownColor: critical,
    });

    series.setData(points);
    chart.timeScale().fitContent();

    return () => {
      chart.remove();
    };
  }, [points]);

  return (
    // `role="figure"`, not `role="img"`: the container also holds the
    // charting library's TradingView attribution link, and `img` is a leaf
    // role — labelling an image that contains a focusable link would make
    // the accessible tree lie about it (axe `nested-interactive`). A figure
    // is a labelled container: the description is announced on entry and
    // the link stays reachable.
    <div
      ref={containerRef}
      role="figure"
      aria-label={`Candlestick chart of ${label}: ${points.length} stored bars. The table below states every value as text.`}
      className="h-72 w-full rounded-xl border border-white/5 bg-black/25"
    />
  );
}

/**
 * The same bars as text: exact strings, one row per bar.
 *
 * The wrapper scrolls, so it is focusable and named: a keyboard-only or
 * screen-reader operator can reach the rows below the fold instead of
 * finding a scroll box they cannot operate (axe
 * `scrollable-region-focusable`).
 */
function BarsTable({ bars }: { readonly bars: BarPoint[] }) {
  return (
    <div
      role="region"
      aria-label="Stored bars table, scrollable"
      tabIndex={0}
      className="max-h-80 overflow-y-auto rounded-xl border border-white/5 bg-black/25 p-4"
    >
      <table className="data-table">
        <caption className="sr-only">The bars charted above, exactly as stored</caption>
        <thead>
          <tr>
            <th scope="col">Timestamp (UTC)</th>
            <th scope="col" className="text-right">
              Open
            </th>
            <th scope="col" className="text-right">
              High
            </th>
            <th scope="col" className="text-right">
              Low
            </th>
            <th scope="col" className="text-right">
              Close
            </th>
            <th scope="col" className="text-right">
              Volume
            </th>
          </tr>
        </thead>
        <tbody>
          {bars.map((bar) => (
            <tr key={bar.timestamp}>
              <td className="font-mono text-xs">{bar.timestamp}</td>
              <td className="text-right font-mono tabular-nums">{bar.open}</td>
              <td className="text-right font-mono tabular-nums">{bar.high}</td>
              <td className="text-right font-mono tabular-nums">{bar.low}</td>
              <td className="text-right font-mono tabular-nums">{bar.close}</td>
              <td className="text-right font-mono tabular-nums">
                {bar.volume === null ? UNKNOWN : bar.volume}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ConnectedBars({ value }: { readonly value: DatasetBarsResponse }) {
  return (
    <div className="space-y-4">
      <p className="text-xs text-muted">
        Read from <span className="uppercase tracking-[0.16em]">dataset version (SHA-256)</span>:{' '}
        <code className="break-all font-mono text-ink">{value.version}</code>
      </p>

      <PriceChart bars={value.bars} label={value.name} />

      <p className="text-xs text-muted">
        {value.has_more
          ? 'The API reports more bars for this window: this chart is one page of the series, not the whole series.'
          : 'The API reports no further bars for this window.'}
      </p>

      <BarsTable bars={value.bars} />
    </div>
  );
}

export function DatasetBars({ name, client = defaultApiClient }: DatasetBarsProps) {
  const state = useDatasetBars(client, name);

  return (
    <section aria-labelledby="dataset-bars-heading" data-state={state.kind} className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h3 id="dataset-bars-heading" className="eyebrow">
          Stored bars
        </h3>
        <p className="flex flex-wrap items-baseline gap-3 text-sm">
          <span role="status" className={'state-chip ' + REQUEST_STATE_TONES[state.kind]}>
            {REQUEST_STATE_LABELS[state.kind]}
          </span>
          <span className="text-muted">{barsNote(state)}</span>
        </p>
      </div>

      {state.kind === 'loading' && (
        // Decorative: the chart that has not arrived, suggested by three
        // flat blocks. The LOADING word above is the announcement.
        <div className="space-y-4" aria-hidden="true">
          <div className="skeleton h-4 w-1/3" />
          <div className="skeleton h-72 w-full" />
        </div>
      )}

      {state.kind === 'connected' && (
        <>
          <p className="text-xs text-muted">
            Instrument{' '}
            <span className="font-mono text-ink">
              {state.value.instrument === null ? UNKNOWN : state.value.instrument}
            </span>{' '}
            · timeframe <span className="font-mono text-ink">{state.value.timeframe}</span> ·
            quality{' '}
            <span className="font-mono text-ink uppercase">{state.value.quality_status}</span>
          </p>

          <ConnectedBars value={state.value} />
        </>
      )}
    </section>
  );
}
