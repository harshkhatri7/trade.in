/**
 * Dataset contract: the read-only view of stored market data.
 *
 * TypeScript mirror of `src/harsh_quant_os/contracts/datasets.py`; the Python
 * models are authoritative. Field names, enum members and the shared fixture
 * are compared in both directions:
 *
 * - `tests/unit/datasets-contract.test.ts` (this side of the comparison)
 * - `tests/api/test_datasets_contract_parity.py` (the Python side)
 *
 * Both read `tests/contracts/datasets.json`, so a payload accepted by one
 * language must be accepted by the other.
 *
 * Two field shapes are deliberate:
 *
 * - **prices are strings.** `Decimal` arrives as a JSON string so that the
 *   digits stored on disk are the digits rendered; parsing to `number` for a
 *   chart is a display step, and the string stays available for the figure
 *   that has to be exact.
 * - **nothing is derived.** These are reads of what validation recorded. No
 *   field is an average, a resample or a fill, because a figure the payload
 *   did not receive would have nowhere in provenance to point back to.
 */

import type { DataQualityStatus, Timeframe } from './index';

/** One dataset: identity, quality verdict, and where its data came from. */
export interface DatasetSummary {
  name: string;
  instrument: string | null;
  timeframe: Timeframe | null;
  quality_status: DataQualityStatus;
  /** SHA-256 of the stored artefact; `null` when nothing is stored. */
  version: string | null;
  storage_path: string | null;
  /** URL or provider name of the most recent acquisition; `null` = not recorded. */
  source: string | null;
  acquired_at: string | null;
  /** Rows recorded at acquisition; `null` = not counted, never zero. */
  row_count: number | null;
  updated_at: string;
}

/** One acquisition record. Append-only: a correction is another entry. */
export interface DatasetProvenanceEntry {
  acquired_at: string;
  source: string;
  /** `null` means *not checked*, never *matched*. */
  checksum_sha256: string | null;
  /** `null` means *not counted*, never *zero*. */
  row_count: number | null;
  notes: string | null;
}

/** `GET /api/v1/datasets`: every dataset, ordered by name. */
export interface DatasetListResponse {
  datasets: DatasetSummary[];
}

/** `GET /api/v1/datasets/{name}`: one dataset plus its acquisition history. */
export interface DatasetDetailResponse {
  dataset: DatasetSummary;
  provenance: DatasetProvenanceEntry[];
}

/** One OHLCV point exactly as stored. Prices are `Decimal` strings. */
export interface BarPoint {
  timestamp: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string | null;
}

/**
 * `GET /api/v1/datasets/{name}/bars`: a page of bars tagged with the version
 * they were read from. The tag is what makes a figure drawn from this payload
 * traceable back to an artefact.
 */
export interface DatasetBarsResponse {
  name: string;
  version: string;
  instrument: string | null;
  timeframe: Timeframe;
  quality_status: DataQualityStatus;
  source: string | null;
  bars: BarPoint[];
  returned: number;
  has_more: boolean;
  /** Timestamp to pass back as `cursor`, or `null` at the end of the series. */
  next_cursor: string | null;
}
