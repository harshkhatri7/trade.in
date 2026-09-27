/**
 * Cross-language contract parity.
 *
 * The Python contracts in `src/harsh_quant_os/` are authoritative. This test
 * fails if the TypeScript mirror drifts, which would let the web layer
 * believe in states that the backend rejects.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  DATA_QUALITY_STATUSES,
  JOB_OPERATIONS,
  JOB_STATUSES,
  MEMORY_CATEGORIES,
  TIMEFRAMES,
  TRADING_MODES,
  isTerminalJobStatus,
  isUsableDataset,
} from '@harsh-quant-os/types';

function readRepoFile(relativePath: string): string {
  return readFileSync(resolve(process.cwd(), relativePath), 'utf8');
}

/** Extract the string values of a Python `StrEnum` class. */
function pythonStrEnumValues(relativePath: string, className: string): string[] {
  const source = readRepoFile(relativePath);
  const classMatch = new RegExp(`class ${className}\\(StrEnum\\):([\\s\\S]*?)\\n\\S`, 'm').exec(
    source,
  );
  if (!classMatch) {
    throw new Error(`Could not find class ${className} in ${relativePath}`);
  }
  const body = classMatch[1] ?? '';
  return [...body.matchAll(/=\s*"([^"]+)"/g)].map((match) => match[1] ?? '');
}

describe('contract parity between Python and TypeScript', () => {
  it('TradingMode matches', () => {
    expect([...TRADING_MODES]).toEqual(
      pythonStrEnumValues('src/harsh_quant_os/safety/gates.py', 'TradingMode'),
    );
  });

  it('JobStatus matches', () => {
    expect([...JOB_STATUSES]).toEqual(
      pythonStrEnumValues('src/harsh_quant_os/contracts/jobs.py', 'JobStatus'),
    );
  });

  it('JobOperation matches', () => {
    expect([...JOB_OPERATIONS]).toEqual(
      pythonStrEnumValues('src/harsh_quant_os/contracts/jobs.py', 'JobOperation'),
    );
  });

  it('DataQualityStatus matches', () => {
    expect([...DATA_QUALITY_STATUSES]).toEqual(
      pythonStrEnumValues('src/harsh_quant_os/contracts/provenance.py', 'DataQualityStatus'),
    );
  });

  it('Timeframe matches', () => {
    expect([...TIMEFRAMES]).toEqual(
      pythonStrEnumValues('src/harsh_quant_os/contracts/provenance.py', 'Timeframe'),
    );
  });

  it('MemoryCategory matches', () => {
    expect([...MEMORY_CATEGORIES]).toEqual(
      pythonStrEnumValues('src/harsh_quant_os/memory/categories.py', 'MemoryCategory'),
    );
  });
});

describe('status helpers', () => {
  it('recognises terminal job states', () => {
    expect(isTerminalJobStatus('succeeded')).toBe(true);
    expect(isTerminalJobStatus('failed')).toBe(true);
    expect(isTerminalJobStatus('cancelled')).toBe(true);
    expect(isTerminalJobStatus('running')).toBe(false);
    expect(isTerminalJobStatus('queued')).toBe(false);
  });

  it('accepts only validated datasets', () => {
    expect(isUsableDataset('valid')).toBe(true);
    expect(isUsableDataset('pending')).toBe(false);
    expect(isUsableDataset('invalid')).toBe(false);
    expect(isUsableDataset('unknown')).toBe(false);
  });
});
