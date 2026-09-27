/**
 * @vitest-environment jsdom
 *
 * End-to-end chain for Phase 1, without a browser automation stack:
 *
 *   real FastAPI process → real HTTP → real API client → real React render
 *
 * The API is started as a genuine uvicorn subprocess on a free port, the same
 * typed client the app uses fetches `/api/v1/health`, and the DOM is asserted
 * to contain the values the server actually returned. Nothing in this test is
 * stubbed except the absence of a browser.
 *
 * The suite skips - loudly - when Python with FastAPI is not available, which
 * is reported by Vitest rather than silently passed. The Python half of the
 * same chain lives in `tests/integration/test_api_http.py`.
 */
import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import { createServer } from 'node:net';
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

  it('serves readiness without claiming a database it does not have', async () => {
    const ready = await fetch(`${baseUrl}${API_PATHS.ready}`);
    const payload = (await ready.json()) as {
      status: string;
      checks: Array<{ name: string; status: string }>;
    };

    expect(ready.status).toBe(200);
    expect(payload.status).toBe('ready');
    const database = payload.checks.find((check) => check.name === 'database');
    expect(database?.status).toBe('not_configured');
  }, 30_000);
});
