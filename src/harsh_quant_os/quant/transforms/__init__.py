"""Research transforms: returns, labels, direction-safe lagging, scaling, splits.

- ``simple_returns`` / ``log_returns`` — period-to-period returns kept
  aligned with the input (documented NaN at position 0);
- ``forward_return`` — a forward-return **label** whose unobservable
  tail is NaN by construction;
- ``lag`` — one-directional shifting that refuses to read the future;
- ``StandardScaler`` — fit/transform scaling whose fit sample is
  explicit and recorded;
- ``chronological_split`` / ``assert_disjoint`` — time-ordered folds
  that assert disjointness before they return.

Not implemented yet (Phase 5, recorded in quant-engine.md §6):
resampling to other bars, timestamp/session alignment, and any
timestamped ``label_time >= info_time`` assertion — those arrive with
the recipe layer that carries real timestamps.
"""

from __future__ import annotations

from harsh_quant_os.quant.series import InvalidSeries
from harsh_quant_os.quant.transforms.lag import lag
from harsh_quant_os.quant.transforms.returns import (
    forward_return,
    log_returns,
    simple_returns,
)
from harsh_quant_os.quant.transforms.scaling import StandardScaler
from harsh_quant_os.quant.transforms.splits import (
    SplitIndices,
    assert_disjoint,
    chronological_split,
)

__all__ = [
    "InvalidSeries",
    "SplitIndices",
    "StandardScaler",
    "assert_disjoint",
    "chronological_split",
    "forward_return",
    "lag",
    "log_returns",
    "simple_returns",
]
