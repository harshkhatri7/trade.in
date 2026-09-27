"""Validate the environment template.

``.env.example`` is the only file that may contain credential-shaped strings,
and every one of them must be an obvious placeholder.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / ".env.example"

PLACEHOLDER_PREFIXES = ("replace-", "changeme", "your-", "todo")
ALLOW_EMPTY = True


def _entries() -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    for raw in TEMPLATE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        lines.append((key.strip(), value.strip()))
    return lines


@pytest.mark.security
def test_template_exists() -> None:
    assert TEMPLATE.is_file(), ".env.example is required"


@pytest.mark.security
def test_every_secret_is_a_placeholder() -> None:
    secret_key = re.compile(r"(SECRET|PASSWORD|TOKEN|API_KEY|API_SECRET|KEY)$", re.IGNORECASE)
    offenders: list[str] = []

    for key, value in _entries():
        if not secret_key.search(key):
            continue
        if value == "" and ALLOW_EMPTY:
            continue
        if value.lower().startswith(PLACEHOLDER_PREFIXES):
            continue
        offenders.append(f"{key}={value}")

    assert not offenders, "Non-placeholder credentials in .env.example:\n" + "\n".join(offenders)


@pytest.mark.security
def test_live_trading_is_disabled_in_template() -> None:
    values = dict(_entries())

    assert values.get("LIVE_TRADING_ENABLED") == "false"
    assert values.get("PAPER_TRADING_ENABLED") == "false"
    assert values.get("BROKER_API_KEY") == ""
    assert values.get("PAPER_CAPITAL_AMOUNT") == "1000"


@pytest.mark.security
def test_template_covers_every_documented_subsystem() -> None:
    keys = {key for key, _ in _entries()}

    required = {
        "AUTH_SECRET_KEY",
        "DATABASE_URL",
        "LOCAL_AGENT_TOKEN",
        "AI_API_KEY",
        "LIVE_TRADING_ENABLED",
        "RISK_MAX_DAILY_LOSS",
        "CLOUD_SYNC_ENABLED",
        "MARKET_DATA_API_KEY",
    }
    missing = required - keys

    assert not missing, f".env.example is missing keys: {sorted(missing)}"


@pytest.mark.security
def test_no_value_looks_like_a_real_credential() -> None:
    suspicious = re.compile(r"^[A-Za-z0-9_\-/+=]{32,}$")
    offenders: list[str] = []

    for key, value in _entries():
        if not suspicious.match(value):
            continue
        if value.lower().startswith(PLACEHOLDER_PREFIXES):
            continue
        if value.lower() in {"postgresql+asyncpg"}:
            continue
        offenders.append(f"{key}={value[:6]}...")

    assert not offenders, f"Long opaque values in template: {offenders}"
