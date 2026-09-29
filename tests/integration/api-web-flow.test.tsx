/**
 * @vitest-environment jsdom
 *
 * End-to-end chain, without a browser automation stack:
 *
 *   real FastAPI process → real HTTP → real API client → real React render
 *
 * The API is started as a genuine uvicorn subprocess on a free port, the same
 * typed client the app uses fetches `/api/v1/health`, and the DOM is asserted
 * to contain the values the server actually returned. Nothing in this test is
 * stubbed except the absence of a browser.
 *
 * The suite skips - loudly - when Python with FastAPI is not available, which
 * is reported by Vitest rather than silently passed. The readiness assertion
 * additionally skips with a printed reason when PostgreSQL is not reachable,
 * because it asserts a round trip that would otherwise be impossible to make.
 * The Python half of the same chain lives in `tests/integration/test_api_http.py`.
 */
import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { connect, createServer } from 'node:net';
import { resolve } from 'node:path';

import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { cleanup, render, screen } from '@testing-library/react';

import { API_PATHS } from '@harsh-quant-os/shared';

import type { ApiClient } from '../../apps/web/src/api-client';
import { createApiClient } from '../../apps/web/src/api-client';
import { SystemStatus } from '../../apps/web/src/components/system-status';

const REPO_ROOT = resolve(process.cwd());
const API_DIR = resolve(REPO_ROOT, 'apps', 'api');
const STARTUP_TIMEOUT_MS = 45_000;
const RENDER_TIMEOUT_MS = 20_000;
const PATH_LIST_SEPARATOR = process.platform === 'win32' ? ';' : ':';

/** Can this interpreter import the API's dependencies? */
function isUsablePython(candidate: string): boolean {
  if (candidate.includes('/') || candidate.includes('\\')) {
    if (!existsSync(candidate)) {
      return false;
    }
  }
  try {
    execFileSync(candidate, ['-c', 'import fastapi, uvicorn'], { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

/**
 * A Python interpreter that can actually import the API's dependencies.
 *
 * `HQOS_PYTHON` is an explicit override: when it is set it is used or the
 * suite skips - it never falls back silently, so an override that does not
 * work is visible instead of being papered over by another interpreter.
 */
function resolveApiPython(): string | null {
  const override = process.env.HQOS_PYTHON;
  if (override !== undefined && override !== '') {
    return isUsablePython(override) ? override : null;
  }

  const candidates = [
    resolve(REPO_ROOT, '.venv', 'Scripts', 'python.exe'),
    resolve(REPO_ROOT, '.venv', 'bin', 'python'),
    'python',
    'python3',
  ];

  for (const candidate of candidates) {
    if (isUsablePython(candidate)) {
      return candidate;
    }
  }
  return null;
}

const apiPython = resolveApiPython();

if (apiPython === null) {
  console.warn(
    '[api-web-flow] SKIPPED: no Python interpreter with fastapi+uvicorn found ' +
      '(install the project with `pip install -e ".[dev]"`, or set HQOS_PYTHON).',
  );
}

/**
 * Where PostgreSQL is configured, without touching the password.
 *
 * Only `DATABASE_HOST` and `DATABASE_PORT` are read out of `.env`; the rest
 * of the file is ignored and never printed, because it holds the credential.
 */
function databaseEndpoint(): { host: string; port: number } {
  let host = '127.0.0.1';
  let port = 5432;

  const envPath = resolve(REPO_ROOT, '.env');
  if (existsSync(envPath)) {
    for (const line of readFileSync(envPath, 'utf8').split(/\r?\n/)) {
      const entry = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/.exec(line);
      if (entry === null) continue;
      const value = (entry[2] ?? '').trim().replace(/^["']|["']$/g, '');
      if (entry[1]?.toUpperCase() === 'DATABASE_HOST' && value !== '') host = value;
      if (entry[1]?.toUpperCase() === 'DATABASE_PORT' && /^\d+$/.test(value)) {
        port = Number(value);
      }
    }
  }
  if (process.env.DATABASE_HOST) host = process.env.DATABASE_HOST;
  if (process.env.DATABASE_PORT && /^\d+$/.test(process.env.DATABASE_PORT)) {
    port = Number(process.env.DATABASE_PORT);
  }
  return { host, port };
}

/** Does anything accept a TCP connection there right now? */
function isListening(host: string, port: number, timeoutMs = 1500): Promise<boolean> {
  return new Promise<boolean>((settle) => {
    const socket = connect({ host, port });
    let settled = false;
    const finish = (reachable: boolean): void => {
      if (settled) return;
      settled = true;
      socket.destroy();
      settle(reachable);
    };
    socket.once('connect', () => finish(true));
    socket.once('error', () => finish(false));
    socket.setTimeout(timeoutMs, () => finish(false));
  });
}

const { host: databaseHost, port: databasePort } = databaseEndpoint();
const databaseListening = (await isListening(databaseHost, databasePort)) === true;

if (!databaseListening) {
  const reason =
    `PostgreSQL is not listening on ${databaseHost}:${databasePort}; ` +
    'the readiness assertion needs a real round trip to pass.';
  if (process.env.HQOS_REQUIRE_POSTGRES === '1') {
    throw new Error(`[api-web-flow] ${reason} (HQOS_REQUIRE_POSTGRES=1 forbids skipping)`);
  }
  console.warn(`[api-web-flow] SKIPPED readiness assertion: ${reason}`);
}

function freePort(): Promise<number> {
  return new Promise((portResolve, portReject) => {
    const server = createServer();
    server.once('error', portReject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (address === null || typeof address === 'string') {
        server.close(() => portReject(new Error('could not allocate a port')));
        return;
      }
      const { port } = address;
      server.close(() => portResolve(port));
    });
  });
}

function delay(ms: number): Promise<void> {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, ms));
}

// Without Python and the API's dependencies there is nothing to start. The
// suite is skipped - visibly, with the warning above - rather than failed or
// silently passed. CI runs a job where Python is installed, so a green run
// there means the chain really executed (.github/workflows/ci.yml).
const describeApiFlow = apiPython === null ? describe.skip : describe;

describeApiFlow('API → API client → DOM', () => {
  let child: ChildProcess | null = null;
  let output = '';
  let baseUrl = '';
  let client: ApiClient | null = null;

  function requirePython(): string {
    if (apiPython === null) {
      throw new Error('Python with fastapi+uvicorn is required; this test must be skipped.');
    }
    return apiPython;
  }

  beforeAll(async () => {
    const python = requirePython();
    const port = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;

    child = spawn(
      python,
      [
        '-m',
        'uvicorn',
        '--app-dir',
        API_DIR,
        'main:app',
        '--host',
        '127.0.0.1',
        '--port',
        String(port),
      ],
      {
        cwd: REPO_ROOT,
        env: {
          ...process.env,
          APP_ENV: 'test',
          LOG_LEVEL: 'WARNING',
          PYTHONPATH: [resolve(REPO_ROOT, 'src'), process.env.PYTHONPATH ?? '']
            .filter(Boolean)
            .join(PATH_LIST_SEPARATOR),
        },
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    );
    child.stdout?.on('data', (chunk: Buffer | string) => {
      output += String(chunk);
    });
    child.stderr?.on('data', (chunk: Buffer | string) => {
      output += String(chunk);
    });

    const deadline = Date.now() + STARTUP_TIMEOUT_MS;
    let lastFailure = 'no attempt made';
    while (Date.now() < deadline) {
      if (child.exitCode !== null) {
        throw new Error(`API exited with code ${child.exitCode}:\n${output}`);
      }
      try {
        const probe = await fetch(`${baseUrl}${API_PATHS.health}`);
        if (probe.ok) {
          lastFailure = '';
          break;
        }
        lastFailure = `status ${probe.status}`;
      } catch (cause) {
        lastFailure = String(cause);
      }
      await delay(200);
    }
    if (lastFailure !== '') {
      throw new Error(
        `API did not start within ${STARTUP_TIMEOUT_MS}ms (${lastFailure}):\n${output}`,
      );
    }

    client = createApiClient({ baseUrl });
  });

  afterEach(() => {
    cleanup();
  });

  afterAll(() => {
    if (child !== null) {
      child.kill();
      child = null;
    }
  });

  it('renders the version and environment the live API returned', async () => {
    const liveClient = client;
    if (liveClient === null) {
      throw new Error('client was not initialised');
    }

    // Independent read of the same server, so the DOM is compared against the
    // API itself and not against anything this test constructed.
    const response = await fetch(`${baseUrl}${API_PATHS.health}`);
    const payload = (await response.json()) as { version: string; environment: string };
    expect(payload.version).toBeTruthy();

    render(<SystemStatus client={liveClient} />);

    expect(
      (await screen.findByText('CONNECTED', {}, { timeout: RENDER_TIMEOUT_MS })).textContent,
    ).toBe('CONNECTED');
    expect(screen.getByText(payload.version)).toBeTruthy();
    expect(screen.getByText(payload.environment)).toBeTruthy();
    expect(screen.getByText(baseUrl)).toBeTruthy();
  }, 60_000);

  it.skipIf(!databaseListening)(
    'serves readiness backed by a database that really answered',
    async () => {
      const ready = await fetch(`${baseUrl}${API_PATHS.ready}`);
      const payload = (await ready.json()) as {
        status: string;
        checks: Array<{ name: string; status: string; detail: string }>;
      };

      expect(ready.status).toBe(200);
      expect(payload.status).toBe('ready');
      const database = payload.checks.find((check) => check.name === 'database');
      expect(database?.status).toBe('ok');
      expect(database?.detail).toBe('PostgreSQL answered a readiness round trip');
    },
    30_000,
  );

  it('never reports a database state it did not earn', async () => {
    const ready = await fetch(`${baseUrl}${API_PATHS.ready}`);
    const payload = (await ready.json()) as {
      status: string;
      checks: Array<{ name: string; status: string }>;
    };
    const database = payload.checks.find((check) => check.name === 'database');

    // `not_configured` would say "there is no database to probe". Phase 2 has
    // one, so the only honest answers are the two a round trip can produce.
    expect(database).toBeDefined();
    expect(['ok', 'failed']).toContain(database?.status);

    // The status code and the check must never disagree: a 200 whose database
    // check failed, or a 503 whose checks all passed, would both be a lie.
    if (ready.status === 200) {
      expect(payload.status).toBe('ready');
      expect(database?.status).toBe('ok');
    } else {
      expect(ready.status).toBe(503);
      expect(payload.status).toBe('not_ready');
      expect(database?.status).toBe('failed');
    }
  }, 30_000);
});
