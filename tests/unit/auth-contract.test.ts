/**
 * Cross-language contract parity for the authentication payloads.
 *
 * The Python models in `src/harsh_quant_os/contracts/auth.py` are
 * authoritative. This test is the TypeScript half of the check and compares,
 * in this direction:
 *
 * 1. the shared fixture parses and round-trips;
 * 2. malformed payloads are rejected - most importantly a payload that grew a
 *    `token`, because the session token lives only in an `HttpOnly` cookie
 *    and must never be readable from JavaScript;
 * 3. the field names written in Python are exactly the ones written in
 *    TypeScript, for every model in the contract.
 *
 * `tests/api/test_auth_contract_parity.py` repeats the comparison from
 * Python, so each CI job fails when either side drifts.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import { parseAuthContextResponse, parseLoginRequest } from '@harsh-quant-os/shared';

const PYTHON_CONTRACT = 'src/harsh_quant_os/contracts/auth.py';
const TYPESCRIPT_CONTRACT = 'packages/types/src/auth.ts';
const FIXTURE_PATH = 'tests/contracts/auth-context.json';

interface AuthFixture {
  auth_context: Record<string, unknown>;
  login_request: Record<string, unknown>;
}

function readRepoFile(relativePath: string): string {
  return readFileSync(resolve(process.cwd(), relativePath), 'utf8');
}

function fixture(): AuthFixture {
  return JSON.parse(readRepoFile(FIXTURE_PATH)) as AuthFixture;
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

describe('auth contract fixture', () => {
  it('parses the auth context exactly as documented', () => {
    const context = fixture().auth_context;

    expect(parseAuthContextResponse(context)).toEqual(context);
  });

  it('parses the login request exactly as documented', () => {
    const request = fixture().login_request;

    expect(parseLoginRequest(request)).toEqual(request);
  });

  it('rejects a payload with an unexpected field', () => {
    const context = { ...fixture().auth_context, extra: 'value' };

    expect(() => parseAuthContextResponse(context)).toThrow(/unexpected fields/);
  });

  it('rejects a payload with a missing half', () => {
    const context = fixture().auth_context;

    expect(() => parseAuthContextResponse({ user: context['user'] })).toThrow(/session/);
  });

  it('rejects a session token smuggled into the payload', () => {
    // The cookie is HttpOnly and the contract has no field for it, so a
    // response that carried one would be refused here rather than rendered.
    const context = { ...fixture().auth_context, token: 'a'.repeat(43) };

    expect(() => parseAuthContextResponse(context)).toThrow(/unexpected fields: token/);
  });

  it('rejects a session id, which grants nothing and leaks a handle', () => {
    const context = fixture().auth_context;

    expect(() => parseAuthContextResponse({ ...context, id: 'abc' })).toThrow(/unexpected fields/);
  });

  it('rejects a user id that is not a UUID', () => {
    const context = fixture().auth_context as { user: Record<string, unknown> };
    const broken = { ...context, user: { ...context.user, id: 'not-a-uuid' } };

    expect(() => parseAuthContextResponse(broken)).toThrow(/user\.id must be a UUID/);
  });

  it('rejects a timestamp the backend could not have written', () => {
    const context = fixture().auth_context as { session: Record<string, unknown> };
    const broken = { ...context, session: { ...context.session, expires_at: 'tomorrow' } };

    expect(() => parseAuthContextResponse(broken)).toThrow(/session\.expires_at must be an ISO/);
  });

  it('accepts a null display name, which is how an unset name arrives', () => {
    const context = fixture().auth_context as { user: Record<string, unknown> };
    const anonymous = { ...context, user: { ...context.user, display_name: null } };

    expect(parseAuthContextResponse(anonymous)).toEqual(anonymous);
  });

  it('rejects empty or oversized credentials before they are posted', () => {
    expect(() => parseLoginRequest({ email: '', password: 'x' })).toThrow(/email must be/);
    expect(() => parseLoginRequest({ email: 'a@example.com', password: '' })).toThrow(
      /password must be/,
    );
    expect(() => parseLoginRequest({ email: 'a'.repeat(255), password: 'x' })).toThrow(
      /at most 254/,
    );
    expect(() => parseLoginRequest({ email: 'a@example.com', password: 'x'.repeat(1025) })).toThrow(
      /at most 1024/,
    );
  });

  it('rejects a non-object payload', () => {
    expect(() => parseAuthContextResponse('ok')).toThrow(/must be an object/);
    expect(() => parseLoginRequest(null)).toThrow(/must be an object/);
  });
});

describe('contract parity between Python and TypeScript', () => {
  for (const name of ['UserProfile', 'SessionProfile', 'AuthContextResponse', 'LoginRequest']) {
    it(`${name} has the same fields on both sides`, () => {
      expect(typescriptInterfaceFields(name)).toEqual(pythonModelFields(name));
    });
  }

  it('no model declares a token or a session id, in either language', () => {
    for (const name of ['UserProfile', 'SessionProfile', 'AuthContextResponse', 'LoginRequest']) {
      for (const forbidden of ['token', 'session_id', 'session_token']) {
        expect(pythonModelFields(name)).not.toContain(forbidden);
        expect(typescriptInterfaceFields(name)).not.toContain(forbidden);
      }
    }
  });
});
