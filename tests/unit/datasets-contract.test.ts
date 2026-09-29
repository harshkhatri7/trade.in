/**
 * Cross-language contract parity for the dataset payloads.
 *
 * The Python models in `src/harsh_quant_os/contracts/datasets.py` are
 * authoritative. This test is the TypeScript half of the check and compares,
 * in this direction:
 *
 * 1. the shared fixture parses and round-trips;
 * 2. malformed payloads are rejected - most importantly a price that arrives
 *    as a JSON number, because the digits stored on disk must not be routed
 *    through a binary float on their way to the screen, and a payload with no
 *    `version`, which would be a figure with nothing to trace back to;
 * 3. the field names written in Python are exactly the ones written in
 *    TypeScript, for every model in the contract.
 *
 * `tests/api/test_datasets_contract_parity.py` repeats the comparison from
 * Python, so each CI job fails when either side drifts.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  datasetBarsPath,
  datasetPath,
  parseDatasetBarsResponse,
  parseDatasetDetailResponse,
  parseDatasetListResponse,
} from '@harsh-quant-os/shared';

const PYTHON_CONTRACT = 'src/harsh_quant_os/contracts/datasets.py';
const TYPESCRIPT_CONTRACT = 'packages/types/src/datasets.ts';
const FIXTURE_PATH = 'tests/contracts/datasets.json';

interface DatasetsFixture {
  dataset_list: Record<string, unknown>;
  dataset_detail: Record<string, unknown>;
  dataset_bars: Record<string, unknown>;
}

function readRepoFile(relativePath: string): string {
  return readFileSync(resolve(process.cwd(), relativePath), 'utf8');
}

function fixture(): DatasetsFixture {
  return JSON.parse(readRepoFile(FIXTURE_PATH)) as DatasetsFixture;
}

/** Field names declared by a Python Pydantic model. */
function pythonModelFields(className: string): string[] {
  const source = readRepoFile(PYTHON_CONTRACT);
  const match = new RegExp(`class ${className}\\(BaseModel\\):([\\s\\S]*?)(?=\\nclass |$)`).exec(
    source,
  );
  if (!match) {
    throw new Error(`class ${className} not found in ${PYTHON_CONTRACT}`);
  }
  const body = match[1] ?? '';
  return [...body.matchAll(/^\s{4}(\w+)\s*:/gm)].map((entry) => entry[1] ?? '');
}

/** Field names declared by a TypeScript interface in the types package. */
function typescriptInterfaceFields(interfaceName: string): string[] {
  const source = readRepoFile(TYPESCRIPT_CONTRACT);
  const match = new RegExp(`export interface ${interfaceName}\\s*\\{([^}]*)\\}`).exec(source);
  if (!match) {
    throw new Error(`interface ${interfaceName} not found in ${TYPESCRIPT_CONTRACT}`);
  }
  const body = match[1] ?? '';
  return [...body.matchAll(/^\s*(\w+)\??:/gm)].map((entry) => entry[1] ?? '');
}

describe('dataset contract fixture', () => {
  it('parses the directory payload exactly as documented', () => {
    const list = fixture().dataset_list;

    expect(parseDatasetListResponse(list)).toEqual(list);
  });

  it('parses the detail payload, keeping both acquisitions', () => {
    const detail = fixture().dataset_detail;

    expect(parseDatasetDetailResponse(detail)).toEqual(detail);
    const parsed = parseDatasetDetailResponse(detail);
    expect(parsed.provenance).toHaveLength(2);
    expect(parsed.dataset.version).toContain('0f27a08b');
  });

  it('parses a page of bars exactly as documented', () => {
    const bars = fixture().dataset_bars;

    expect(parseDatasetBarsResponse(bars)).toEqual(bars);
    expect(parseDatasetBarsResponse(bars).has_more).toBe(true);
  });

  it('rejects a payload with an unexpected field', () => {
    const list = { ...fixture().dataset_list, extra: 'value' };

    expect(() => parseDatasetListResponse(list)).toThrow(/unexpected fields/);
  });

  it('rejects a summary missing a field the contract always carries', () => {
    const list = fixture().dataset_list as { datasets: Record<string, unknown>[] };
    const { version, ...withoutVersion } = list.datasets[0] ?? {};

    expect(version).toBeDefined();
    expect(() => parseDatasetListResponse({ datasets: [{ ...withoutVersion }] })).toThrow(
      /version must be/,
    );
  });

  it('rejects a quality status the backend cannot have recorded', () => {
    const list = fixture().dataset_list as { datasets: Record<string, unknown>[] };
    const first = list.datasets[0] ?? {};

    expect(() =>
      parseDatasetListResponse({ datasets: [{ ...first, quality_status: 'verified' }] }),
    ).toThrow(/must be one of/);
  });

  it('rejects a price that arrived as a JSON number', () => {
    const bars = fixture().dataset_bars as { bars: Record<string, unknown>[] };
    const mutated = bars.bars.map((point, index) =>
      index === 0 ? { ...point, open: 78563 } : point,
    );

    expect(() => parseDatasetBarsResponse({ ...fixture().dataset_bars, bars: mutated })).toThrow(
      /open must be a non-empty string/,
    );
  });

  it('rejects a price that is not written as a decimal', () => {
    const bars = fixture().dataset_bars as { bars: Record<string, unknown>[] };

    for (const bad of ['not-a-price', '1,234.5']) {
      const mutated = bars.bars.map((point, index) =>
        index === 0 ? { ...point, open: bad } : point,
      );

      expect(() => parseDatasetBarsResponse({ ...fixture().dataset_bars, bars: mutated })).toThrow(
        /open must be a decimal number written as a string/,
      );
    }
  });

  it('rejects a page with no version, which would leave a figure untraceable', () => {
    const bars = fixture().dataset_bars;
    const { version, ...withoutVersion } = bars as Record<string, unknown>;

    expect(version).toBeDefined();
    expect(() => parseDatasetBarsResponse(withoutVersion)).toThrow(/version must be/);
  });

  it('rejects a page whose count contradicts its bars', () => {
    const bars = { ...fixture().dataset_bars, returned: 0 };

    expect(() => parseDatasetBarsResponse(bars)).toThrow(/returned says 0 but 2 bars/);
  });

  it('rejects a page that claims more data without a cursor', () => {
    const bars = { ...fixture().dataset_bars, has_more: true, next_cursor: null };

    expect(() => parseDatasetBarsResponse(bars)).toThrow(/has_more is true but no next_cursor/);
  });

  it('rejects a non-object payload', () => {
    expect(() => parseDatasetListResponse('ok')).toThrow(/must be an object/);
    expect(() => parseDatasetDetailResponse(null)).toThrow(/must be an object/);
  });

  it('keeps a null volume, which is how a provider without one arrives', () => {
    const bars = fixture().dataset_bars as { bars: Record<string, unknown>[] };
    const withoutVolume = {
      ...fixture().dataset_bars,
      bars: bars.bars.map((point) => ({ ...point, volume: null })),
    };

    const parsed = parseDatasetBarsResponse(withoutVolume);
    expect(parsed.bars[0]?.volume).toBeNull();
    expect(parsed.returned).toBe(parsed.bars.length);
  });
});

describe('dataset paths', () => {
  it('spells the versioned directory once', () => {
    expect(datasetPath('kraken.xbtusd.1h')).toBe('/api/v1/datasets/kraken.xbtusd.1h');
    expect(datasetBarsPath('kraken.xbtusd.1h')).toBe('/api/v1/datasets/kraken.xbtusd.1h/bars');
  });

  it('encodes a name containing a separator as one path component', () => {
    expect(datasetPath('group/name')).toBe('/api/v1/datasets/group%2Fname');
  });
});

describe('contract parity between Python and TypeScript', () => {
  for (const name of [
    'DatasetSummary',
    'DatasetProvenanceEntry',
    'DatasetListResponse',
    'DatasetDetailResponse',
    'BarPoint',
    'DatasetBarsResponse',
  ]) {
    it(`${name} has the same fields on both sides`, () => {
      expect(typescriptInterfaceFields(name)).toEqual(pythonModelFields(name));
    });
  }
});
