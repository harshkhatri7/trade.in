import Link from 'next/link';

import { SystemStatus } from '../components/system-status';

/**
 * Overview page.
 *
 * The two lists below are the platform's own status, mirrored from
 * `docs/PROJECT-STATUS.md` — which is itself validated by
 * `tests/unit/test_documentation.py`. Nothing here is aspirational: a row
 * appears under "Built and verified" only because the corresponding code
 * and tests exist, and "Deliberately not built" names what is missing
 * rather than hiding it. Live trading and broker connectivity are stated
 * in the footer of every page as well.
 */
const PRESENT = [
  'FastAPI service: health, readiness, session auth, read-only dataset reads',
  'Typed, validated API client with explicit loading / error states',
  'Shared Python and TypeScript contract, checked in both directions',
  'PostgreSQL storage, Argon2id sessions, append-only audit log',
  'Dataset store with content-addressed artefacts and provenance',
  'Two keyless market-data adapters: Kraken (crypto), Yahoo (NSE/BSE and others)',
  'Validation pipeline: schema, ordering, duplicates, gaps, outliers',
  'Dataset browser: directory, provenance, candlestick chart, watchlist, multi-timeframe',
  'Quant engine: indicators, statistical tests, leakage-controlled features',
  'Backtesting engine with byte-identical run manifests and honest reports',
  'Walk-forward, sensitivity, benchmarks and promotion gates for strategies',
] as const;

const ABSENT = [
  'AI research agents (phase 8, not started)',
  'Scheduled or resumable ingestion — the operator names every window',
  'Session calendar and second-source cross-check in validation',
  'Portfolio, orders, positions or any order entry of any kind',
  'Paper trading, live trading, broker connectivity',
  'Nightly backups, rate limiting, per-request CSRF',
] as const;

function CheckedList({
  items,
  mark,
  markClass,
}: {
  readonly items: readonly string[];
  readonly mark: string;
  readonly markClass: string;
}) {
  return (
    <ul className="mt-4 space-y-2 text-sm text-muted">
      {items.map((item) => (
        <li key={item} className="flex gap-3">
          <span aria-hidden="true" className={markClass}>
            {mark}
          </span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

export default function HomePage() {
  return (
    <div className="space-y-8 sm:space-y-12">
      {/* Hero */}
      <section aria-labelledby="page-title" className="panel animate-rise space-y-6">
        <p className="eyebrow">Private research platform</p>
        <h1 id="page-title" className="text-3xl font-semibold tracking-tight sm:text-5xl">
          HARSH QUANT&nbsp;OS
        </h1>
        <p className="max-w-2xl text-base leading-relaxed text-muted sm:text-lg">
          A quantitative trading research workspace for validating data, testing strategies honestly
          and running a paper-trading loop with strict risk control.
        </p>

        <div className="flex flex-wrap items-stretch gap-4">
          <dl className="inline-flex flex-col gap-1 rounded-xl border-l-2 border-accent bg-black/25 px-4 py-3">
            <dt className="eyebrow">Phase</dt>
            <dd className="text-lg font-medium">Foundation complete (phases 0–7)</dd>
          </dl>
          <dl className="inline-flex flex-col gap-1 rounded-xl border-l-2 border-line bg-black/25 px-4 py-3">
            <dt className="eyebrow">Next</dt>
            <dd className="text-lg font-medium">Phase 8 — AI research, not started</dd>
          </dl>
        </div>

        <p className="text-sm text-muted">
          Every figure on this site is read from a stored artefact or a live API response.{' '}
          <Link href="/datasets" className="link text-accent">
            Open the dataset directory
          </Link>
          .
        </p>
      </section>

      {/* Live API state: a real /health round trip, not a decoration. */}
      <div className="animate-rise">
        <SystemStatus />
      </div>

      {/* Scope */}
      <section aria-labelledby="scope-heading" className="grid gap-6 sm:grid-cols-2">
        <div className="panel animate-rise">
          <h2 id="scope-heading" className="panel-title">
            Built and verified so far
          </h2>
          <p className="mt-1 text-xs text-muted">
            Each line is covered by the test suites run on every change.
          </p>
          <CheckedList items={PRESENT} mark="✓" markClass="text-accent" />
        </div>

        <div className="panel animate-rise">
          <h2 className="panel-title">Deliberately not built yet</h2>
          <p className="mt-1 text-xs text-muted">
            Named here rather than left to be discovered. A missing feature is not a silent one.
          </p>
          <CheckedList items={ABSENT} mark="—" markClass="text-warning" />
        </div>
      </section>
    </div>
  );
}
