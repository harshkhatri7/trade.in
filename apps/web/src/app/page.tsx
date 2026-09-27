import { SystemStatus } from '../components/system-status';

const PRESENT = [
  'FastAPI service with /health and /ready',
  'Typed, validated API client',
  'Shared Python / TypeScript contract',
  'Strict typing, linting, formatting and tests',
];

const ABSENT = [
  'Database (PostgreSQL arrives in Phase 2)',
  'Market data, charts or indicators',
  'Strategies, signals or backtests',
  'AI agents, orders, positions or trading',
];

export default function HomePage() {
  return (
    <div className="space-y-12">
      <section aria-labelledby="page-title" className="space-y-6">
        <p className="text-xs uppercase tracking-[0.28em] text-muted">Private research platform</p>
        <h1 id="page-title" className="text-4xl font-semibold tracking-tight sm:text-6xl">
          HARSH QUANT OS
        </h1>
        <p className="max-w-2xl text-lg leading-relaxed text-muted">
          A quantitative trading research workspace for validating data, testing strategies honestly
          and running a paper-trading loop with strict risk control.
        </p>

        <dl className="inline-flex flex-col gap-1 border-l-2 border-accent pl-4">
          <dt className="text-xs uppercase tracking-[0.24em] text-muted">Phase</dt>
          <dd className="text-xl font-medium">Foundation / Application Skeleton</dd>
        </dl>
      </section>

      <SystemStatus />

      <section aria-labelledby="scope-heading" className="grid gap-6 sm:grid-cols-2">
        <div className="rounded-lg border border-line p-6">
          <h2 id="scope-heading" className="text-sm font-semibold uppercase tracking-[0.18em]">
            Implemented in this phase
          </h2>
          <ul className="mt-4 space-y-2 text-sm text-muted">
            {PRESENT.map((item) => (
              <li key={item} className="flex gap-3">
                <span aria-hidden="true" className="text-accent">
                  ✓
                </span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-lg border border-line p-6">
          <h2 className="text-sm font-semibold uppercase tracking-[0.18em]">
            Deliberately not built yet
          </h2>
          <ul className="mt-4 space-y-2 text-sm text-muted">
            {ABSENT.map((item) => (
              <li key={item} className="flex gap-3">
                <span aria-hidden="true" className="text-warning">
                  —
                </span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
