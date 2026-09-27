"""Documentation integrity tests.

These are the checks from STEP 24 of the foundation protocol: the required
documents must exist, relative links must resolve, and no document may make
profit claims that the system cannot honour.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_FILES: tuple[str, ...] = (
    "README.md",
    "AGENTS.md",
    "ARCHITECTURE.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    ".env.example",
    ".gitignore",
    ".gitattributes",
    "pyproject.toml",
    "package.json",
    "tsconfig.json",
    "docs/ROADMAP.md",
    "docs/PROJECT-STATUS.md",
    "docs/architecture/system-architecture.md",
    "docs/architecture/frontend.md",
    "docs/architecture/backend.md",
    "docs/architecture/database.md",
    "docs/architecture/data-platform.md",
    "docs/architecture/quant-engine.md",
    "docs/architecture/backtesting.md",
    "docs/architecture/risk-engine.md",
    "docs/architecture/ai-system.md",
    "docs/architecture/local-agent.md",
    "docs/architecture/synchronization.md",
    "docs/development/development-workflow.md",
    "docs/development/testing-strategy.md",
    "docs/development/git-workflow.md",
    "docs/development/coding-standards.md",
    "docs/development/definition-of-done.md",
    "docs/development/agent-workflow.md",
    "docs/security/threat-model.md",
    "docs/security/secrets-management.md",
    "docs/security/local-agent-security.md",
    "docs/security/broker-security.md",
    "docs/operations/deployment.md",
    "docs/operations/backup.md",
    "docs/operations/disaster-recovery.md",
    "docs/operations/monitoring.md",
    "docs/research/research-methodology.md",
    "docs/research/backtesting-methodology.md",
    "docs/research/anti-overfitting.md",
    "docs/research/experiment-protocol.md",
    "docs/decisions/ADR-0001-initial-architecture.md",
)

AGENT_DIRECTORIES: tuple[str, ...] = (
    "architect",
    "frontend",
    "backend",
    "data",
    "quant",
    "ai",
    "risk",
    "security",
    "qa",
    "auditor",
)

AGENT_REQUIRED_SECTIONS: tuple[str, ...] = (
    "Mission",
    "Responsibilities",
    "Permitted directories",
    "Prohibited directories",
    "Tools",
    "Required context",
    "Workflow",
    "Testing requirements",
    "Documentation requirements",
    "Handoff format",
    "Definition of done",
)

# Phrases that must never appear: the project does not promise returns.
FORBIDDEN_CLAIMS: tuple[str, ...] = (
    "guaranteed profit",
    "guaranteed returns",
    "risk-free profit",
    "cannot lose",
    "always profitable",
    "profit guarantee",
)

_LINK_PATTERN = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")
_FENCE = re.compile(r"^```")


@pytest.mark.unit
def test_required_files_exist() -> None:
    missing = [name for name in REQUIRED_FILES if not (REPO_ROOT / name).is_file()]

    assert not missing, "Missing required files:\n" + "\n".join(missing)


@pytest.mark.unit
def test_agent_specifications_exist_with_required_sections() -> None:
    problems: list[str] = []
    for agent in AGENT_DIRECTORIES:
        spec = REPO_ROOT / "agents" / agent / "AGENT.md"
        if not spec.is_file():
            problems.append(f"agents/{agent}/AGENT.md is missing")
            continue
        text = spec.read_text(encoding="utf-8")
        for section in AGENT_REQUIRED_SECTIONS:
            if f"## {section}" not in text:
                problems.append(f"agents/{agent}/AGENT.md missing section '## {section}'")
    assert not problems, "\n".join(problems)


@pytest.mark.unit
def test_agents_index_lists_every_agent() -> None:
    readme = REPO_ROOT / "agents" / "README.md"
    assert readme.is_file(), "agents/README.md index is required"
    text = readme.read_text(encoding="utf-8")
    for agent in AGENT_DIRECTORIES:
        assert agent in text, f"agents/README.md does not index the {agent} agent"


def _markdown_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*.md"):
        if any(part in {".git", "node_modules", ".venv"} for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def _relative_links(path: Path) -> list[str]:
    links: list[str] = []
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if _FENCE.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in _LINK_PATTERN.finditer(line):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            links.append(target.split("#", 1)[0])
    return [link for link in links if link]


@pytest.mark.unit
def test_relative_markdown_links_resolve() -> None:
    broken: list[str] = []
    for path in _markdown_files():
        for link in _relative_links(path):
            if link.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", link):
                target = REPO_ROOT / link.lstrip("/")
            else:
                target = (path.parent / link).resolve()
            if not target.exists():
                broken.append(f"{path.relative_to(REPO_ROOT).as_posix()} -> {link}")
    assert not broken, "Broken documentation links:\n" + "\n".join(broken)


@pytest.mark.unit
def test_no_profit_guarantee_language_anywhere() -> None:
    offenders: list[str] = []
    for path in _markdown_files():
        text = path.read_text(encoding="utf-8").lower()
        for claim in FORBIDDEN_CLAIMS:
            if claim in text:
                offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}: '{claim}'")
    assert not offenders, "Disallowed claims found:\n" + "\n".join(offenders)


@pytest.mark.unit
def test_roadmap_lists_every_phase_in_order() -> None:
    roadmap = (REPO_ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    expected = [
        "PHASE 0",
        "PHASE 1",
        "PHASE 2",
        "PHASE 3",
        "PHASE 4",
        "PHASE 5",
        "PHASE 6",
        "PHASE 7",
        "PHASE 8",
        "PHASE 9",
        "PHASE 10",
        "PHASE 11",
        "PHASE 12",
        "PHASE 13",
        "PHASE 14",
        "PHASE 15",
        "PHASE 16",
        "PHASE 17",
    ]
    positions = [roadmap.upper().find(phase) for phase in expected]

    assert all(pos >= 0 for pos in positions), "Roadmap must contain PHASE 0..PHASE 17"
    assert positions == sorted(positions), "Roadmap phases must appear in order"


@pytest.mark.unit
def test_project_status_states_current_phase_and_disabled_live_trading() -> None:
    status = (REPO_ROOT / "docs" / "PROJECT-STATUS.md").read_text(encoding="utf-8")

    assert "0.1.0-alpha" in status
    assert "DISABLED" in status
    assert "NOT CONNECTED" in status
    assert "1,000" in status or "1000" in status
