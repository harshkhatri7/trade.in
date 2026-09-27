"""Integration: start the real API over TCP, call it, shut it down.

This is the "smallest reliable integration test" the brief asks for instead of
Playwright: a genuine HTTP round trip against a genuine uvicorn process, with
the same payload the web client parses. The browser-side half of the chain
(API client -> component -> DOM) is covered by
``tests/integration/api-web-flow.test.ts``.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx2
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "apps" / "api"
STARTUP_TIMEOUT_SECONDS = 30.0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env["APP_ENV"] = "test"
    env["LOG_LEVEL"] = "WARNING"
    env["PYTHONPATH"] = os.pathsep.join(
        path for path in (str(REPO_ROOT / "src"), env.get("PYTHONPATH", "")) if path
    )
    return env


def _wait_until_healthy(process: subprocess.Popen[str], base_url: str) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    last_error = "no attempt made"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            pytest.fail(f"API exited with code {process.returncode}:\n{output}")
        try:
            response = httpx2.get(f"{base_url}/api/v1/health", timeout=1.0)
            if response.status_code == 200:
                return
            last_error = f"status {response.status_code}"
        except httpx2.HTTPError as exc:
            last_error = str(exc)
        time.sleep(0.2)
    output = process.stdout.read() if process.stdout else ""
    pytest.fail(
        f"API did not become healthy within {STARTUP_TIMEOUT_SECONDS}s ({last_error}):\n{output}"
    )


@pytest.mark.integration
def test_api_serves_health_and_ready_over_real_http() -> None:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "--app-dir",
            str(API_DIR),
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )

    try:
        _wait_until_healthy(process, base_url)

        health = httpx2.get(f"{base_url}/api/v1/health", timeout=5.0)
        assert health.status_code == 200
        payload: dict[str, Any] = health.json()
        assert payload["status"] == "ok"
        assert payload["service"] == "harsh-quant-os-api"
        assert payload["version"]

        # The unversioned alias must answer identically for probes.
        alias = httpx2.get(f"{base_url}/health", timeout=5.0)
        assert alias.status_code == 200
        assert alias.json() == payload

        ready = httpx2.get(f"{base_url}/api/v1/ready", timeout=5.0)
        assert ready.status_code == 200
        ready_payload: dict[str, Any] = ready.json()
        assert ready_payload["status"] == "ready"
        database = next(c for c in ready_payload["checks"] if c["name"] == "database")
        assert database["status"] == "not_configured"

        # Structured errors still apply over real HTTP.
        missing = httpx2.get(f"{base_url}/no-such-path", timeout=5.0)
        assert missing.status_code == 404
        assert missing.headers["content-type"].startswith("application/problem+json")
        assert missing.json()["title"] == "Not Found"
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)
        # Close the pipe: an unclosed file object collected later surfaces as an
        # unraisable-exception warning in an unrelated test.
        if process.stdout is not None:
            process.stdout.close()
