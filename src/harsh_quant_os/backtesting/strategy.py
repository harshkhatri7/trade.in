"""The strategy contract: what a strategy sees, and what it may return.

A strategy in this engine is a **deterministic decision rule**. Once per
bar, after that bar closes, the engine hands it a
:class:`DecisionContext` and asks for a target position. The contract is
deliberately narrow:

- **No future access.** ``context.history`` is a bounded view ending at
  the current bar. Indexing past the end raises ``IndexError`` even
  though the underlying dataset continues — a strategy physically
  cannot read a bar it has not been given (backtesting.md §2 Causality,
  enforced here rather than by convention).
- **No execution authority.** A strategy returns a *desired position*;
  it never sees an order API, a fill, or a portfolio to mutate. The
  engine owns sequencing, costs and the risk evaluation (backtesting.md
  §6: "The strategy supplies intent, not orders").
- **No hidden time.** The context carries bars and ledger state; it
  carries no wall clock, no RNG, no global state. Two runs of the same
  strategy over the same bars produce the same decisions.

Money enters as ``Decimal`` and leaves as ``Decimal``: a target
position is an exact quantity (fractional sizes are meaningful for
crypto), and floats are refused rather than silently rounded
(backtesting-methodology.md §2 "exact numerics; no floating-point
money").
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, overload, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from harsh_quant_os.data.providers import Bar

__all__ = ["DecisionContext", "HistoryView", "Strategy", "closes_as_float"]


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """Everything a strategy may know at one bar's close — and nothing later.

    Attributes:
        history: Bars ``0..current`` inclusive as a :class:`HistoryView`
            (bounded; see its docstring for the access rules).
        bar: The current bar — ``history[-1]``, the bar whose close this
            decision is made on.
        position: Current signed quantity (exact), after any fill that
            already happened on this bar.
        cash: Current cash (exact), after any fill already on this bar.
        equity: Marked at this bar's close (``cash + position * close``).
    """

    history: Sequence[Bar]
    bar: Bar
    position: Decimal
    cash: Decimal
    equity: Decimal


class HistoryView(Sequence[Bar]):
    """A read-only, bounded view of bars: ``bars[0:stop]``.

    Behaves like the tuple it bounds, with one extra rule that is the
    whole point: **indices at or past ``stop`` raise ``IndexError``,
    even though the underlying sequence continues. The future is not
    addressable from inside a decision.

    Slicing is clamped to the bound (``view[:10_000]`` never reaches
    beyond the current bar), negative indices address the view's own
    tail, and iteration yields exactly the visible bars.
    """

    __slots__ = ("_bars", "_stop")

    def __init__(self, bars: Sequence[Bar], stop: int) -> None:
        if stop < 0 or stop > len(bars):
            raise IndexError(
                f"history bound {stop} is outside 0..{len(bars)}: the view covers "
                "bars that do not exist"
            )
        self._bars = bars
        self._stop = stop

    def __len__(self) -> int:
        return self._stop

    @overload
    def __getitem__(self, index: int) -> Bar: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[Bar]: ...

    def __getitem__(self, index: int | slice) -> Bar | Sequence[Bar]:
        if isinstance(index, slice):
            start, stop, step = index.indices(self._stop)
            return tuple(self._bars[i] for i in range(start, stop, step))
        position = index
        if position < 0:
            position += self._stop
        if position < 0 or position >= self._stop:
            noun = "bar" if self._stop == 1 else "bars"
            raise IndexError(
                f"history is bounded at {self._stop} {noun}: index {index} is out of "
                "range. A strategy cannot read past the current bar "
                "(backtesting.md section 2, Causality)"
            )
        return self._bars[position]

    def __iter__(self) -> Iterator[Bar]:
        for position in range(self._stop):
            yield self._bars[position]


@runtime_checkable
class Strategy(Protocol):
    """A deterministic decision rule over a bounded history.

    Implementations must be pure functions of the context: no wall
    clock, no randomness, no state carried between runs (a fresh
    instance per run is the safe pattern; the engine may call
    :meth:`describe` and :meth:`decide` in any interleaving).
    """

    name: str

    def decide(self, context: DecisionContext) -> Decimal | None:
        """Return the desired **target position** (signed quantity), or None.

        ``None`` means "no opinion, no order". Returning the current
        ``context.position`` also produces no order — the engine
        computes ``target - position`` and skips zero deltas.

        The returned quantity is exact: ``Decimal`` or ``int``. Floats
        and booleans are refused by the engine rather than rounded.

        Args:
            context: The bounded world at this bar's close.

        Returns:
            The signed quantity the position should become, or None.
        """
        ...

    def describe(self) -> Mapping[str, str]:
        """Name and parameters for the run manifest, as strings.

        Every value must be a ``str``: manifests are canonical JSON
        (backtesting.md §4), and a parameter that cannot be written as
        one is not recorded — so it is refused instead. Sorted by the
        engine, so construction order cannot change the manifest.
        """
        ...


def closes_as_float(bars: Sequence[Bar]) -> NDArray[np.float64]:
    """Close prices as float64 for indicator arithmetic.

    The one documented conversion boundary: money stays ``Decimal``
    (ledger, fills, equity), while indicators from
    ``harsh_quant_os.quant`` run on float64 by their own validated
    contract. Prices converted here are read-only inputs to a decision,
    never the ledger's numbers.
    """
    return np.array([float(bar.close) for bar in bars], dtype=np.float64)
