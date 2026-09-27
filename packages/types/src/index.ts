/**
 * Shared domain types for HARSH QUANT OS.
 *
 * These mirror the Python contracts in `src/harsh_quant_os/`. When a type
 * changes on one side it must change on the other; drift is caught by the
 * tests in `tests/unit`.
 */

/** Execution modes, least to most dangerous. Live is unreachable in Phase 0-15. */
export type TradingMode = 'disabled' | 'paper' | 'live';

export const TRADING_MODES: readonly TradingMode[] = ['disabled', 'paper', 'live'];

/** Lifecycle of a local-agent job. */
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export const JOB_STATUSES: readonly JobStatus[] = [
  'queued',
  'running',
  'succeeded',
  'failed',
  'cancelled',
];

export const TERMINAL_JOB_STATUSES: readonly JobStatus[] = ['succeeded', 'failed', 'cancelled'];

/** Operations the local agent may perform (allowlist, never a menu). */
export type JobOperation =
  'dataset.scan' | 'dataset.build_features' | 'backtest.run' | 'model.train';

export const JOB_OPERATIONS: readonly JobOperation[] = [
  'dataset.scan',
  'dataset.build_features',
  'backtest.run',
  'model.train',
];

/** Validation outcome attached to every ingested dataset. */
export type DataQualityStatus = 'unknown' | 'pending' | 'valid' | 'suspect' | 'invalid';

export const DATA_QUALITY_STATUSES: readonly DataQualityStatus[] = [
  'unknown',
  'pending',
  'valid',
  'suspect',
  'invalid',
];

/** Standardised bar sizes. Provider labels are normalised into these. */
export type Timeframe = 'tick' | '1m' | '5m' | '15m' | '30m' | '1h' | '4h' | '1d' | '1w' | '1mo';

export const TIMEFRAMES: readonly Timeframe[] = [
  'tick',
  '1m',
  '5m',
  '15m',
  '30m',
  '1h',
  '4h',
  '1d',
  '1w',
  '1mo',
];

/**
 * Persistent research memory partitions. The database is the source of truth;
 * AI conversational memory is never authoritative.
 */
export type MemoryCategory =
  'market' | 'strategy' | 'experiment' | 'trade' | 'research' | 'journal' | 'model' | 'system';

export const MEMORY_CATEGORIES: readonly MemoryCategory[] = [
  'market',
  'strategy',
  'experiment',
  'trade',
  'research',
  'journal',
  'model',
  'system',
];

/** True when a job has reached a final state. */
export function isTerminalJobStatus(status: JobStatus): boolean {
  return TERMINAL_JOB_STATUSES.includes(status);
}

/** True when a dataset passed validation. */
export function isUsableDataset(status: DataQualityStatus): boolean {
  return status === 'valid';
}
