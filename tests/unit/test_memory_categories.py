"""The research-memory vocabulary is closed: eight categories, no extras.

The categories are mirrored in TypeScript and compared against this file by
`tests/unit/contract-parity.test.ts`, so a category added on one side only
would fail there. These tests pin the Python side itself: the exact set, its
uniqueness, and that membership behaves like a plain string (which is what
the database and the API both treat it as).
"""

from __future__ import annotations

import pytest

from harsh_quant_os.memory import MEMORY_CATEGORIES, MemoryCategory

EXPECTED_VALUES = (
    "market",
    "strategy",
    "experiment",
    "trade",
    "research",
    "journal",
    "model",
    "system",
)


@pytest.mark.unit
def test_categories_are_the_documented_eight() -> None:
    assert tuple(category.value for category in MemoryCategory) == EXPECTED_VALUES


@pytest.mark.unit
def test_frozenset_covers_every_category() -> None:
    assert isinstance(MEMORY_CATEGORIES, frozenset)
    assert frozenset(MemoryCategory) == MEMORY_CATEGORIES
    assert len(MEMORY_CATEGORIES) == len(EXPECTED_VALUES)


@pytest.mark.unit
def test_values_are_unique() -> None:
    assert len(set(EXPECTED_VALUES)) == len(EXPECTED_VALUES)


@pytest.mark.unit
def test_members_behave_as_their_string_value() -> None:
    for category in MemoryCategory:
        assert isinstance(category, str)
        assert str(category) == category.value
        assert MemoryCategory(category.value) is category
        assert category in MEMORY_CATEGORIES
