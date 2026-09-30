"""Version-pinned input data for a backtest.

The engine's data boundary: bars come from the same content-addressed
store the quant recipes read, through the same verification function
(:func:`~harsh_quant_os.quant.recipes.bars.load_stored_bars`) — name
safety, artefact hash against its directory, complete volume — but the
exact ``Decimal`` prices are **kept**, not converted to float64.
backtesting-methodology.md §2: "Cash: exact numerics; no floating-point
money". The price side of money starts as the stored decimal.

:class:`BacktestData` validates at construction so the engine loop can
assume one symbol, one timeframe and strictly increasing
timezone-aware timestamps — the sequencing rules of backtesting.md §2
rest on that assumption being checked, not hoped for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from harsh_quant_os.backtesting.errors import BacktestError
from harsh_quant_os.data.providers import Bar
from harsh_quant_os.quant.recipes import load_stored_bars

__all__ = ["BacktestData", "load_backtest_data"]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class BacktestData:
    """One dataset's bars, pinned by content-addressed version.

    Attributes:
        dataset_id: Dataset name, e.g. ``kraken.xbtusd.1m``.
        version: 64-character SHA-256 of the clean artefact — the same
            identity the run manifest records (backtesting.md §4).
        bars: The bars, in stored chronological order, as validated
            ``Bar`` objects (timezone-aware timestamps, exact decimals).

    Raises:
        BacktestError: Empty dataset, missing/invalid pin, more than one
        symbol or timeframe, or timestamps that are not strictly
        increasing (duplicated or out-of-order bars are refused here so
        the engine's strict-time loop never has to guess).
    """

    dataset_id: str
    version: str
    bars: tuple[Bar, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bars", tuple(self.bars))
        if not self.dataset_id or not self.dataset_id.strip():
            raise BacktestError("dataset_id must not be empty")
        if not _SHA256_RE.fullmatch(self.version):
            raise BacktestError(
                f"dataset version must be a 64-character lowercase SHA-256, got {self.version!r}"
            )
        if not self.bars:
            raise BacktestError("a backtest dataset carries at least one bar, got 0")

        symbols = {bar.symbol for bar in self.bars}
        if len(symbols) != 1:
            raise BacktestError(
                f"a backtest runs one instrument; this dataset has {len(symbols)}: "
                + ", ".join(sorted(symbols))
            )
        timeframes = {bar.timeframe for bar in self.bars}
        if len(timeframes) != 1:
            raise BacktestError(
                f"a backtest runs one timeframe; this dataset has "
                f"{len(timeframes)}: " + ", ".join(sorted(tf.value for tf in timeframes))
            )

        for index in range(1, len(self.bars)):
            previous = self.bars[index - 1]
            current = self.bars[index]
            if current.timestamp <= previous.timestamp:
                raise BacktestError(
                    f"bar times must strictly increase: bar {index} at "
                    f"{current.timestamp.isoformat()} does not follow bar {index - 1} at "
                    f"{previous.timestamp.isoformat()} (refused, never reordered)"
                )

    @property
    def start(self) -> datetime:
        """Timestamp of the first bar (timezone-aware)."""
        return self.bars[0].timestamp

    @property
    def end(self) -> datetime:
        """Timestamp of the last bar (timezone-aware)."""
        return self.bars[-1].timestamp

    @property
    def symbol(self) -> str:
        """The dataset's single instrument, e.g. ``XBTUSD``."""
        return self.bars[0].symbol

    @property
    def timeframe(self) -> str:
        """The dataset's timeframe value, e.g. ``1m``."""
        return self.bars[0].timeframe.value


def load_backtest_data(root: Path, name: str, *, version: str | None = None) -> BacktestData:
    """Load a stored clean dataset as :class:`BacktestData`.

    Delegates verification to
    :func:`~harsh_quant_os.quant.recipes.bars.load_stored_bars` (its
    refusals — unknown dataset, ambiguous versions, hash mismatch,
    empty, missing volume — propagate unchanged), then applies this
    layer's sequencing validation.

    Args:
        root: The data root (the directory holding ``clean/``).
        name: Dataset name; a plain directory name.
        version: Stored version to load, or ``None`` for the dataset's
            only version.

    Returns:
        The pinned dataset, exact decimals intact.

    Raises:
        RecipeError: Anything the store boundary refuses.
        BacktestError: The bars fail this layer's validation.
    """
    version, bars = load_stored_bars(root, name, version=version)
    return BacktestData(dataset_id=name, version=version, bars=tuple(bars))
