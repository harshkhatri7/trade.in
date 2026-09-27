"""Repository secret scan.

Walks the working tree and fails if anything that looks like a real credential
is committed or staged. Template files (``*.example``) are excluded because
they legitimately contain placeholder text.

The scanner is deliberately dependency-free so it runs in CI without
downloading binaries. It is a safety net, not a substitute for review.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "coverage",
        "dist",
        "build",
        ".next",
        "logs",
        ".cache",
    }
)

EXCLUDED_SUFFIXES = (
    ".example",
    ".pyc",
    ".pyo",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".whl",
    ".parquet",
    ".feather",
    ".arrow",
    ".sqlite",
    ".db",
)

MAX_BYTES = 5 * 1024 * 1024

PLACEHOLDER_HINTS = (
    "replace-",
    "replace_with",
    "changeme",
    "change-me",
    "example",
    "placeholder",
    "your-",
    "your_",
    "local-dev",
    "not-a-real",
    "dummy",
    "test-only",
)

# Patterns are built from fragments so that this file does not match itself.
_ASSIGNMENT = (
    r"(?:api[_-]?key|api[_-]?secret|client[_-]?secret|secret|password|passwd|token)"
    r"\s*[=:]\s*[\"']([A-Za-z0-9_\-/+=]{24,})[\"']"
)

PATTERNS: dict[str, re.Pattern[str]] = {
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "aws access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github token": re.compile(r"\bgh" + r"[pousr]_" + r"[A-Za-z0-9]{36,}\b"),
    "slack token": re.compile(r"\bxox" + r"[baprs]-" + r"[A-Za-z0-9-]{10,}\b"),
    "credential assignment": re.compile(_ASSIGNMENT, re.IGNORECASE),
}


def _iter_candidate_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        if path.name == ".env":
            continue  # git-ignored local file; its presence is expected
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
        except OSError:
            continue
        files.append(path)
    return sorted(files)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


@pytest.mark.security
def test_no_secret_patterns_in_repository() -> None:
    offenders: list[str] = []
    for path in _iter_candidate_files():
        relative = path.relative_to(REPO_ROOT).as_posix()
        text = _read(path)
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                candidate = match.group(1) if match.groups() else match.group(0)
                lowered = candidate.lower()
                if any(hint in lowered for hint in PLACEHOLDER_HINTS):
                    continue
                offenders.append(f"{relative}: {label}: {candidate[:12]}...")

    assert not offenders, "Potential secrets found:\n" + "\n".join(offenders)


@pytest.mark.security
def test_env_file_is_ignored_by_git() -> None:
    gitignore = _read(REPO_ROOT / ".gitignore")

    assert "\n.env\n" in gitignore + "\n", ".env must be git-ignored"
    assert ".env.*" in gitignore, "environment variants must be git-ignored"
    assert "!.env.example" in gitignore, "the template must stay tracked"
    assert "node_modules/" in gitignore
    assert "__pycache__/" in gitignore
    assert ".venv/" in gitignore


@pytest.mark.security
def test_no_env_file_contains_a_secret_placeholder_free_value() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        pytest.skip("no local .env file present")

    text = _read(env_path)
    # The local .env must never be tracked; only assert it is not world-readable
    # content that looks like a production credential.
    assert "AKIA" not in text, "local .env appears to contain an AWS key"
