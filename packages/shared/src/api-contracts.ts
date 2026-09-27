/**
 * Runtime validation of the API payloads the browser is allowed to render.
 *
 * TypeScript types disappear at runtime, and a network response is `unknown`
 * until something checks it. These parsers are the check: they accept exactly
 * what the Python models accept - same fields, same values, no extras - and
 * throw a `TypeError` describing the difference otherwise.
 *
 * Mirrors `harsh_quant_os.contracts.system`. Never render a payload that did
 * not pass through here.
 */

import type {
  ApiEnvironment,
  CheckStatus,
  HealthResponse,
  HealthStatus,
  ReadinessCheck,
  ReadinessStatus,
  ReadyResponse,
} from '@harsh-quant-os/types';
import {
  API_ENVIRONMENTS,
  CHECK_STATUSES,
  HEALTH_STATUSES,
  READINESS_STATUSES,
} from '@harsh-quant-os/types';

/** Paths served by the API. The versioned pair is the contract; the rest are aliases. */
export const API_PATHS = {
  health: '/api/v1/health',
  ready: '/api/v1/ready',
  aliasHealth: '/health',
  aliasReady: '/ready',
} as const;

type JsonObject = Record<string, unknown>;

function asObject(value: unknown, label: string): JsonObject {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`);
  }
  return value as JsonObject;
}

function readString(object: JsonObject, key: string, label: string): string {
  const value = object[key];
  if (typeof value !== 'string' || value.length === 0) {
    throw new TypeError(`${label} must be a non-empty string`);
  }
  return value;
}

function readOneOf<T extends string>(
  object: JsonObject,
  key: string,
  allowed: readonly T[],
  label: string,
): T {
  const value = object[key];
  if (typeof value !== 'string' || !allowed.includes(value as T)) {
    throw new TypeError(`${label} must be one of: ${allowed.join(', ')}`);
  }
  return value as T;
}

function rejectUnknownKeys(object: JsonObject, allowed: readonly string[], label: string): void {
  const unexpected = Object.keys(object).filter((key) => !allowed.includes(key));
  if (unexpected.length > 0) {
    throw new TypeError(`${label} has unexpected fields: ${unexpected.join(', ')}`);
  }
}

const HEALTH_FIELDS = ['status', 'service', 'version', 'environment'] as const;
const READINESS_CHECK_FIELDS = ['name', 'status', 'detail'] as const;
const READY_FIELDS = ['status', 'service', 'version', 'environment', 'checks'] as const;

/** Validate one readiness check. */
export function parseReadinessCheck(value: unknown, label = 'readiness check'): ReadinessCheck {
  const object = asObject(value, label);
  rejectUnknownKeys(object, READINESS_CHECK_FIELDS, label);
  return {
    name: readString(object, 'name', `${label}.name`),
    status: readOneOf<CheckStatus>(object, 'status', CHECK_STATUSES, `${label}.status`),
    detail: readString(object, 'detail', `${label}.detail`),
  };
}

/** Validate a `/health` payload. */
export function parseHealthResponse(value: unknown): HealthResponse {
  const label = 'health response';
  const object = asObject(value, label);
  rejectUnknownKeys(object, HEALTH_FIELDS, label);
  return {
    status: readOneOf<HealthStatus>(object, 'status', HEALTH_STATUSES, `${label}.status`),
    service: readString(object, 'service', `${label}.service`),
    version: readString(object, 'version', `${label}.version`),
    environment: readOneOf<ApiEnvironment>(
      object,
      'environment',
      API_ENVIRONMENTS,
      `${label}.environment`,
    ),
  };
}

/** Validate a `/ready` payload, including every readiness check. */
export function parseReadyResponse(value: unknown): ReadyResponse {
  const label = 'ready response';
  const object = asObject(value, label);
  rejectUnknownKeys(object, READY_FIELDS, label);
  const rawChecks = object['checks'];
  if (!Array.isArray(rawChecks)) {
    throw new TypeError(`${label}.checks must be an array`);
  }
  return {
    status: readOneOf<ReadinessStatus>(object, 'status', READINESS_STATUSES, `${label}.status`),
    service: readString(object, 'service', `${label}.service`),
    version: readString(object, 'version', `${label}.version`),
    environment: readOneOf<ApiEnvironment>(
      object,
      'environment',
      API_ENVIRONMENTS,
      `${label}.environment`,
    ),
    checks: rawChecks.map((check, index) => parseReadinessCheck(check, `checks[${index}]`)),
  };
}
