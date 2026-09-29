"""Start a genuine uvicorn process and wait for it to answer.

Shared by the integration tests that need HTTP rather than an in-process ASGI
call: a real socket, real headers, a real ``Set-Cookie`` - the things an ASGI
transport approximates well enough for most assertions but cannot prove.

``_running_api`` deliberately waits for *liveness* (``/api/v1/health``) rather
than readiness (``/api/v1/ready``). The process has to come up whether or not
its database is reachable, otherwise the tests whose subject is a database
that is down could never begin.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx2
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "apps" / "api"
STARTUP_TIMEOUT_SECONDS = 30.0

# Nothing listens on this loopback port, so a connection is refused at once.
# Used to prove the *down* path; it never depends on the state of the machine.
UNREACHABLE_DATABASE_URL = (
    "postgresql+asyncpg://integration_tests:integration_tests@127.0.0.1:5/integration_tests"
)


def free_port() -> int:
    """Ask the kernel for a port nobody is holding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The child process environment: test profile, importable packages."""
    env = dict(os.environ)
    env["APP_ENV"] = "test"
    env["LOG_LEVEL"] = "WARNING"
    env["PYTHONPATH"] = os.pathsep.join(
        path for path in (str(REPO_ROOT / "src"), env.get("PYTHONPATH", "")) if path
    )
    if extra:
        env.update(extra)
    return env


def wait_until_healthy(process: subprocess.Popen[str], base_url: str) -> None:
    """Block until the process answers ``/api/v1/health`` with 200."""
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


@contextmanager
def running_api(
    extra_env: dict[str, str] | None = None,
    *,
    cwd: Path = REPO_ROOT,
) -> Iterator[str]:
    """Run a real uvicorn process and hand back its base URL.

    ``cwd`` is the directory the process runs from and therefore where its
    relative paths resolve. It defaults to the repository root; a test that
    passes a temporary directory gets an application whose dataset store
    lives inside that directory rather than in the workspace, so the test
    can write a store of its own without touching real files. Every path the
    child needs to import is absolute, so changing the directory changes
    only what the process resolves at run time, not what it can load.
    """
    port = free_port()
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
        cwd=cwd,
        env=subprocess_env(extra_env),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    try:
        wait_until_healthy(process, base_url)
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)
        # Close the pipe: an unclosed file object collected later surfaces as
        # an unraisable-exception warning in an unrelated test.
        if process.stdout is not None:
            process.stdout.close()


__all__ = [
    "API_DIR",
    "REPO_ROOT",
    "STARTUP_TIMEOUT_SECONDS",
    "UNREACHABLE_DATABASE_URL",
    "free_port",
    "running_api",
    "subprocess_env",
    "wait_until_healthy",
]
