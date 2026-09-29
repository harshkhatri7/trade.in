/**
 * Runtime validation of the API payloads the browser is allowed to render.
 *
 * TypeScript types disappear at runtime, and a network response is `unknown`
 * until something checks it. These parsers are the check: they accept exactly
 * what the Python models accept - same fields, same values, no extras - and
 * throw a `TypeError` describing the difference otherwise.
 *
 * Mirrors `harsh_quant_os.contracts.system` and `harsh_quant_os.contracts.auth`.
 * Never render a payload that did not pass through here.
 */

import type {
  ApiEnvironment,
  AuthContextResponse,
  CheckStatus,
  HealthResponse,
  HealthStatus,
  LoginRequest,
  ReadinessCheck,
  ReadinessStatus,
  ReadyResponse,
  SessionProfile,
  UserProfile,
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

const AUTH_CONTEXT_FIELDS = ['user', 'session'] as const;
const USER_PROFILE_FIELDS = ['id', 'email', 'display_name', 'is_superuser', 'created_at'] as const;
const SESSION_PROFILE_FIELDS = ['issued_at', 'expires_at'] as const;
const LOGIN_REQUEST_FIELDS = ['email', 'password'] as const;

/**
 * Canonical 8-4-4-4-12 UUID, which is the only spelling the API writes.
 *
 * Python's `uuid.UUID` also accepts undashed and braced forms on input, but it
 * never emits them: `model_dump(mode="json")` always produces this one, and
 * this parser runs against what the API produced.
 */
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function readBoolean(object: JsonObject, key: string, label: string): boolean {
  const value = object[key];
  if (typeof value !== 'boolean') {
    throw new TypeError(`${label} must be a boolean`);
  }
  return value;
}

function readNullableString(object: JsonObject, key: string, label: string): string | null {
  const value = object[key];
  if (value === null) {
    return null;
  }
  if (typeof value !== 'string') {
    throw new TypeError(`${label} must be a string or null`);
  }
  return value;
}

function readUuid(object: JsonObject, key: string, label: string): string {
  const value = readString(object, key, label);
  if (!UUID_PATTERN.test(value)) {
    throw new TypeError(`${label} must be a UUID`);
  }
  return value;
}

/** A timestamp the API could have written: parseable, and kept verbatim. */
function readTimestamp(object: JsonObject, key: string, label: string): string {
  const value = readString(object, key, label);
  if (Number.isNaN(Date.parse(value))) {
    throw new TypeError(`${label} must be an ISO-8601 timestamp`);
  }
  return value;
}

/** A non-empty string bounded exactly as the Pydantic field is. */
function readBoundedString(
  object: JsonObject,
  key: string,
  maxLength: number,
  label: string,
): string {
  const value = readString(object, key, label);
  if (value.length > maxLength) {
    throw new TypeError(`${label} must be at most ${maxLength} characters`);
  }
  return value;
}

/** Validate the `user` half of an auth context. */
export function parseUserProfile(value: unknown, label = 'user'): UserProfile {
  const object = asObject(value, label);
  rejectUnknownKeys(object, USER_PROFILE_FIELDS, label);
  return {
    id: readUuid(object, 'id', `${label}.id`),
    email: readString(object, 'email', `${label}.email`),
    display_name: readNullableString(object, 'display_name', `${label}.display_name`),
    is_superuser: readBoolean(object, 'is_superuser', `${label}.is_superuser`),
    created_at: readTimestamp(object, 'created_at', `${label}.created_at`),
  };
}

/** Validate the `session` half of an auth context. */
export function parseSessionProfile(value: unknown, label = 'session'): SessionProfile {
  const object = asObject(value, label);
  rejectUnknownKeys(object, SESSION_PROFILE_FIELDS, label);
  return {
    issued_at: readTimestamp(object, 'issued_at', `${label}.issued_at`),
    expires_at: readTimestamp(object, 'expires_at', `${label}.expires_at`),
  };
}

/**
 * Validate the answer to "who am I?", served by both login and `/me`.
 *
 * Note what this refuses to carry: a token, and a session id. Neither exists
 * in the contract, so a payload that introduced one is rejected here instead
 * of reaching the renderer - the cookie is HttpOnly and must stay unreadable.
 */
export function parseAuthContextResponse(value: unknown): AuthContextResponse {
  const label = 'auth context';
  const object = asObject(value, label);
  rejectUnknownKeys(object, AUTH_CONTEXT_FIELDS, label);
  return {
    user: parseUserProfile(object['user'], `${label}.user`),
    session: parseSessionProfile(object['session'], `${label}.session`),
  };
}

/** Validate credentials before they are posted. */
export function parseLoginRequest(value: unknown): LoginRequest {
  const label = 'login request';
  const object = asObject(value, label);
  rejectUnknownKeys(object, LOGIN_REQUEST_FIELDS, label);
  return {
    email: readBoundedString(object, 'email', 254, `${label}.email`),
    password: readBoundedString(object, 'password', 1024, `${label}.password`),
  };
}
