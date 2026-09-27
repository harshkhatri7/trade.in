"""Persistent research memory categories.

The database is the source of truth for project state. The AI research
assistant may *read* these categories and *propose* new entries; it may never
overwrite history or rely on conversational memory for anything that affects
a result.
"""

from __future__ import annotations

from enum import StrEnum


class MemoryCategory(StrEnum):
    """Top-level partition of the persistent research memory."""

    MARKET = "market"
    STRATEGY = "strategy"
    EXPERIMENT = "experiment"
    TRADE = "trade"
    RESEARCH = "research"
    JOURNAL = "journal"
    MODEL = "model"
    SYSTEM = "system"


MEMORY_CATEGORIES: frozenset[MemoryCategory] = frozenset(MemoryCategory)
