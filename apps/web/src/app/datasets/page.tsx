import type { Metadata } from 'next';

import { DatasetBrowser } from '../../components/dataset-browser';

export const metadata: Metadata = {
  title: 'Datasets · HARSH QUANT OS',
  description:
    'Read-only view of ingested market data: provenance, quality status and dataset versions.',
};

export default function DatasetsPage() {
  return (
    <div className="space-y-10">
      <section aria-labelledby="page-title" className="space-y-4">
        <p className="text-xs uppercase tracking-[0.28em] text-muted">Market data</p>
        <h1 id="page-title" className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Datasets
        </h1>
        <p className="max-w-2xl leading-relaxed text-muted">
          Everything ingested into this workspace, what validation recorded about it, and the
          artefact version each figure was read from. This page is read-only: it cannot change
          stored data, and a value that was never recorded shows as a dash rather than as zero.
        </p>
      </section>

      <DatasetBrowser />
    </div>
  );
}
