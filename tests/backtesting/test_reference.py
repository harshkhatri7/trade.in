"""Reference-strategy contract: pure decisions, honest description.

``hqos backtest report`` runs :class:`CloseThreshold`, so its rule must
be exactly what the manifest records: enter at or above the entry band,
flat at or below the exit band, hold in between — a pure function of
the bar and the current position, no memory of previous bars. Its
parameters are refused unless they can be stated honestly: ``Decimal``
only (a float never reaches a sizing rule), finite only, an entry
strictly above its exit, and no exit under an unconditional entry
(which could never fire and must not be recordable as a rule that
exists).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from harsh_quant_os.backtesting import BacktestError, CloseThreshold, DecisionContext
from tests.backtesting.test_engine import GOLDEN_BARS, _bar

pytestmark = pytest.mark.backtesting


def _context(*, close: str, position: str) -> DecisionContext:
    """A decision whose current bar closes at ``close``."""
    bar = _bar(0, close, close)
    return DecisionContext(
        history=GOLDEN_BARS,
        bar=bar,
        position=Decimal(position),
        cash=Decimal(1000),
        equity=Decimal(1000),
    )


def test_it_enters_holds_and_exits_on_the_stated_bands() -> None:
    strategy = CloseThreshold(
        target_qty=Decimal("0.5"),
        entry_above=Decimal(110),
        exit_below=Decimal(90),
    )

    # Entry band hit: target the size.
    assert strategy.decide(_context(close="115", position="0")) == Decimal("0.5")
    # Inside the bands: hold what is held — pure in (bar, position).
    assert strategy.decide(_context(close="100", position="0")) == Decimal(0)
    assert strategy.decide(_context(close="100", position="0.5")) == Decimal("0.5")
    # Exit band hit: target flat.
    assert strategy.decide(_context(close="85", position="0.5")) == Decimal(0)
    # Re-entry from flat: back to the size.
    assert strategy.decide(_context(close="111", position="0")) == Decimal("0.5")


def test_unconditional_entry_never_exits_and_says_so() -> None:
    strategy = CloseThreshold(target_qty=Decimal(2))

    assert strategy.decide(_context(close="1", position="0")) == Decimal(2)
    assert strategy.describe() == {
        "entry": "always",
        "exit": "never",
        "target_qty": "2",
    }


def test_describe_states_every_parameter_for_the_manifest() -> None:
    strategy = CloseThreshold(
        target_qty=Decimal("0.5"),
        entry_above=Decimal(110),
        exit_below=Decimal(90),
    )

    assert strategy.describe() == {
        "entry": "close >= 110",
        "exit": "close <= 90",
        "target_qty": "0.5",
    }


def test_parameters_that_cannot_be_stated_honestly_are_refused() -> None:
    with pytest.raises(BacktestError, match="must be a Decimal"):
        CloseThreshold(target_qty=0.5)  # type: ignore[arg-type]
    with pytest.raises(BacktestError, match="must be finite"):
        CloseThreshold(target_qty=Decimal("NaN"))
    with pytest.raises(BacktestError, match="never trigger"):
        CloseThreshold(target_qty=Decimal(1), exit_below=Decimal(90))
    with pytest.raises(BacktestError, match="strictly above"):
        CloseThreshold(
            target_qty=Decimal(1),
            entry_above=Decimal(90),
            exit_below=Decimal(110),
        )
    with pytest.raises(BacktestError, match="strictly above"):
        CloseThreshold(
            target_qty=Decimal(1),
            entry_above=Decimal(90),
            exit_below=Decimal(90),
        )
