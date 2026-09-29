/**
 * Cross-language contract parity for the system status payloads.
 *
 * The Python models in `src/harsh_quant_os/contracts/system.py` are
 * authoritative. This test is the TypeScript half of the check and compares,
 * in this direction:
 *
 * 1. the shared fixture parses and round-trips;
 * 2. malformed payloads are rejected (the browser never renders them);
 * 3. the field names and enum values written in Python are exactly the ones
 *    written in TypeScript.
 *
 * `tests/api/test_contract_parity.py` repeats the comparison from Python, so
 * each CI job fails when either side drifts.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  API_ENVIRONMENTS,
  CHECK_STATUSES,
  HEALTH_STATUSES,
  READINESS_STATUSES,
} from '@harsh-quant-os/types';
import { parseHealthResponse, parseReadyResponse } from '@harsh-quant-os/shared';

const PYTHON_CONTRACT = 'src/harsh_quant_os/contracts/system.py';
const TYPESCRIPT_CONTRACT = 'packages/types/src/system.ts';
const FIXTURE_PATH = 'tests/contracts/system-status.json';

interface SharedFixture {
  health: Record<string, unknown>;
  ready: Record<string, unknown>;
}

function readRepoFile(relativePath: string): string {
  return readFileSync(resolve(process.cwd(), relativePath), 'utf8');
}

function fixture(): SharedFixture {
  return JSON.parse(readRepoFile(FIXTURE_PATH)) as SharedFixture;
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

/** Values assigned by a Python StrEnum class. */
function pythonEnumValues(className: string): string[] {
  const source = readRepoFile(PYTHON_CONTRACT);
  const match = new RegExp(`class ${className}\\(StrEnum\\):([\\s\\S]*?)(?=\\nclass |$)`).exec(
    source,
  );
  if (!match) {
    throw new Error(`class ${className} not found in ${PYTHON_CONTRACT}`);
  }
  const body = match[1] ?? '';
  return [...body.matchAll(/=\s*"([^"]+)"/g)].map((entry) => entry[1] ?? '');
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

describe('system status contract fixture', () => {
  it('parses the health payload exactly as documented', () => {
    const health = fixture().health;

    expect(parseHealthResponse(health)).toEqual(health);
  });

  it('parses the ready payload exactly as documented', () => {
    const ready = fixture().ready;

    expect(parseReadyResponse(ready)).toEqual(ready);
  });

  it('rejects a payload with an unexpected field', () => {
    const health = { ...fixture().health, extra: 'value' };

    expect(() => parseHealthResponse(health)).toThrow(/unexpected fields/);
  });

  it('rejects a payload with a missing field', () => {
    const health = fixture().health as Record<string, unknown>;
    const { version: _version, ...withoutVersion } = health;

    expect(() => parseHealthResponse(withoutVersion)).toThrow(/version/);
  });

  it('rejects a status the backend would never send', () => {
    const health = { ...fixture().health, status: 'healthy' };

    expect(() => parseHealthResponse(health)).toThrow(/status must be one of/);
  });

  it('rejects a readiness check with an unknown state', () => {
    const ready = fixture().ready as { checks: Array<Record<string, unknown>> };
    const broken = {
      ...ready,
      checks: ready.checks.map((check) =>
        check.name === 'database' ? { ...check, status: 'unchecked' } : check,
      ),
    };

    expect(() => parseReadyResponse(broken)).toThrow(/checks\[\d+\]\.status/);
  });

  it('still accepts not_configured, which Phase 2 no longer serves', () => {
    // The database check now reports `ok` or `failed` because a round trip is
    // performed. `not_configured` remains part of the shared vocabulary for a
    // dependency that was never set up, so both language mirrors must keep
    // accepting it even though nothing emits it today.
    const ready = fixture().ready as { checks: Array<Record<string, unknown>> };
    const legacy = {
      ...ready,
      checks: ready.checks.map((check) =>
        check.name === 'database' ? { ...check, status: 'not_configured' } : check,
      ),
    };

    expect(parseReadyResponse(legacy)).toEqual(legacy);
  });

  it('rejects a non-object payload', () => {
    expect(() => parseHealthResponse('ok')).toThrow(/must be an object/);
    expect(() => parseReadyResponse(null)).toThrow(/must be an object/);
  });
});

describe('contract parity between Python and TypeScript', () => {
  it('HealthResponse has the same fields on both sides', () => {
    expect(typescriptInterfaceFields('HealthResponse')).toEqual(
      pythonModelFields('HealthResponse'),
    );
  });

  it('ReadyResponse has the same fields on both sides', () => {
    expect(typescriptInterfaceFields('ReadyResponse')).toEqual(pythonModelFields('ReadyResponse'));
  });

  it('ReadinessCheck has the same fields on both sides', () => {
    expect(typescriptInterfaceFields('ReadinessCheck')).toEqual(
      pythonModelFields('ReadinessCheck'),
    );
  });

  it('HealthStatus matches', () => {
    expect([...HEALTH_STATUSES]).toEqual(pythonEnumValues('HealthStatus'));
  });

  it('ReadinessStatus matches', () => {
    expect([...READINESS_STATUSES]).toEqual(pythonEnumValues('ReadinessStatus'));
  });

  it('CheckStatus matches', () => {
    expect([...CHECK_STATUSES]).toEqual(pythonEnumValues('CheckStatus'));
  });

  it('ApiEnvironment matches', () => {
    expect([...API_ENVIRONMENTS]).toEqual(pythonEnumValues('ApiEnvironment'));
  });
});
