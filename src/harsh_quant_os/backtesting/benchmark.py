"""The passive benchmark: what the same universe did without a strategy.

anti-overfitting.md §2.6 requires comparing against "a passive
benchmark of the same universe" before a result means anything. This
benchmark is a *fixed rule evaluated over the window*, not a strategy:
it decides nothing, so there is no look-ahead to guard against and no
risk gate to pass. Its honesty job is to state its assumptions beside
its numbers (methodology §4's closing rule) and to answer for its
arithmetic, which the dataclass re-derives on construction.

Design commitments:

- **Same first opportunity.** It fills on the window's second bar's
  open — the first price any strategy can act on, since a strategy
  cannot decide before the window starts — adjusted by the run's own
  slippage model exactly as the engine adjusts a buy.
- **Same costs, provably affordable.** The configured commission
  model is applied to the entry by its own method, and the size is
  solved as a fixed point of ``notional + commission(notional) =
  capital`` with a downward adjustment loop that guarantees the spend
  never exceeds the starting capital: the cash residue is never
  negative, and a commission model that would eat the capital or
  never settle is refused rather than approximated.
- **Same marking.** The position is held to the window's final close
  and marked with no exit fee — exactly how the engine's ending
  equity marks an open position. Exit costs are charged to neither
  side of the comparison.
- **Long only.** A short passive reference would need borrow and
  financing costs this engine does not model; none is invented.
- **Recomputable, not stored.** The result is a pure function of the
  pinned data and the config, so it is computed where it is used
  instead of being written down and trusted later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from harsh_quant_os.backtesting.data import BacktestData
from harsh_quant_os.backtesting.engine import BacktestConfig
from harsh_quant_os.backtesting.errors import BacktestError

__all__ = ["PassiveBenchmark", "passive_benchmark"]


@dataclass(frozen=True, slots=True)
class PassiveBenchmark:
    """One long-only passive reference over a pinned window.

    Attributes:
        entry_time: When the position was taken — the second bar's
            timestamp (the first fill opportunity).
        entry_reference: That bar's open, before slippage.
        entry_price: What a buy fills at (slippage applied by the
            model's own method).
        quantity: Units held, sized so entry + commission fit the
            starting capital exactly.
        commission: Charged at entry by the configured model.
        cash_left: Starting capital minus entry spend and commission;
            never negative.
        last_close: The window's final close, the marking price.
        ending_equity: ``quantity * last_close + cash_left`` — marked,
            not liquidated.
        net_return: ``ending_equity / starting_capital - 1``.
        bars: Window length.
        starting_capital: The capital the rule starts from.
        assumptions: The rule's stated assumptions (§4's closing rule:
            a metric without them is not reported).

    Raises:
        BacktestError: A window or figure that cannot account for
        itself — the spend identity, the ending identity or the net
        return must all follow from the recorded fields, and an
        empty assumptions tuple is refused.
    """

    entry_time: datetime
    entry_reference: Decimal
    entry_price: Decimal
    quantity: Decimal
    commission: Decimal
    cash_left: Decimal
    last_close: Decimal
    ending_equity: Decimal
    net_return: Decimal
    bars: int
    starting_capital: Decimal
    assumptions: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.bars < 2:
            raise BacktestError(
                f"a passive benchmark fills on the second bar, so it needs at "
                f"least two bars, got {self.bars}"
            )
        if self.starting_capital <= 0:
            raise BacktestError(
                f"the benchmark starts from capital {self.starting_capital}: "
                "starting capital must be positive"
            )
        for name, value in (
            ("entry_reference", self.entry_reference),
            ("entry_price", self.entry_price),
            ("quantity", self.quantity),
            ("last_close", self.last_close),
        ):
            if not value.is_finite() or value <= 0:
                raise BacktestError(
                    f"the benchmark's {name} must be a positive finite decimal, got {value}"
                )
        for name, value in (("commission", self.commission), ("cash_left", self.cash_left)):
            if not value.is_finite() or value < 0:
                raise BacktestError(
                    f"the benchmark's {name} must be a non-negative finite decimal, got {value}"
                )
        if not self.ending_equity.is_finite() or not self.net_return.is_finite():
            raise BacktestError(
                f"the benchmark's ending equity and net return must be finite, "
                f"got {self.ending_equity} and {self.net_return}"
            )
        if not self.assumptions:
            raise BacktestError(
                "a benchmark without its assumptions is not reported (methodology section 4)"
            )
        for key, statement in self.assumptions:
            if not key.strip() or not statement.strip():
                raise BacktestError(
                    "every assumption needs a name and a statement; an empty "
                    f"one is refused ({key!r}: {statement!r})"
                )

        spent = self.quantity * self.entry_price + self.commission
        if spent + self.cash_left != self.starting_capital:
            raise BacktestError(
                f"the benchmark spends {spent} and holds {self.cash_left} but "
                f"started from {self.starting_capital}: a benchmark that cannot "
                "account for its own capital is refused, not smoothed over"
            )
        ending = self.quantity * self.last_close + self.cash_left
        if ending != self.ending_equity:
            raise BacktestError(
                f"the benchmark records ending equity {self.ending_equity} but "
                f"{self.quantity} at {self.last_close} plus {self.cash_left} is "
                f"{ending}: a benchmark that cannot account for its own "
                "marking is refused"
            )
        net = self.ending_equity / self.starting_capital - 1
        if net != self.net_return:
            raise BacktestError(
                f"the benchmark records net return {self.net_return} but "
                f"{self.ending_equity} / {self.starting_capital} - 1 is {net}: "
                "a benchmark that cannot account for its own return is refused"
            )


#: What the benchmark is and is not, attached to every instance.
_ASSUMPTIONS: tuple[tuple[str, str], ...] = (
    (
        "direction",
        "long only: a short passive reference would need borrow costs this "
        "engine does not model, and none is invented",
    ),
    (
        "entry",
        "the window's second bar open plus the configured slippage — the "
        "first fill opportunity any strategy gets; a strategy cannot act "
        "before the window starts",
    ),
    (
        "sizing",
        "starting capital spent on the position with its commission; the "
        "residue stays as cash and is never negative",
    ),
    (
        "marking",
        "held to the window's final close and marked with no exit fee — the "
        "same marking the engine gives an open position, so neither side of "
        "the comparison pays an exit the other does not",
    ),
    (
        "costs",
        "the configured commission and slippage models, each applied by its own method",
    ),
    (
        "role",
        "a passive reference, not a strategy: it decides nothing, so no risk "
        "evaluation applies to it and no run manifest is written",
    ),
)

#: How many fixed-point steps the commission solve may take before the
#: model is declared un-settled. Generous for any sane model (a bps
#: rate converges in under ten); a refusal, never an approximation.
_MAX_FEE_STEPS = 100


def passive_benchmark(data: BacktestData, *, config: BacktestConfig) -> PassiveBenchmark:
    """Evaluate the same-universe passive rule over a pinned window.

    Args:
        data: The pinned bars — the same window a comparison run used.
        config: Starting capital and the cost models, identical to the
            run being compared against.

    Returns:
        The benchmark with its assumptions attached.

    Raises:
        BacktestError: Fewer than two bars, a non-positive close or
        entry reference, a slippage model that prices the entry at or
        below zero, a commission model that would eat the capital or
        does not settle within the step budget, or a size that cannot
        be brought under the capital.
    """
    bars = data.bars
    if len(bars) < 2:
        raise BacktestError(
            f"a passive benchmark fills on the first opportunity like every "
            f"strategy: {len(bars)} bar(s) leave no second bar to fill on — "
            "the engine's own two-bar floor applies"
        )
    capital = config.starting_capital
    if capital <= 0:
        raise BacktestError(
            f"the benchmark starts from capital {capital}: starting capital must be positive"
        )
    for index, bar in enumerate(bars):
        if bar.close <= 0:
            raise BacktestError(
                f"bar {index} closes at {bar.close}: a passive rule holds "
                "units to that close, and non-positive prices break both the "
                "holding and the marking"
            )
    reference = bars[1].open
    if reference <= 0:
        raise BacktestError(
            f"the second bar opens at {reference}: the benchmark's entry reference must be positive"
        )
    entry_price = config.slippage.apply(reference, buy=True)
    if entry_price <= 0:
        raise BacktestError(
            f"the slippage model turned {reference} into {entry_price}: a "
            "benchmark cannot buy at a non-positive price"
        )

    # Size by fixed point: the largest notional whose total spend
    # (notional + commission) equals the capital. Proportional models
    # settle immediately or geometrically; anything that does not
    # settle within the budget is refused, not approximated.
    notional = capital
    for _ in range(_MAX_FEE_STEPS):
        fee = config.commission.apply(notional)
        following = capital - fee
        if following <= 0:
            raise BacktestError(
                f"at capital {capital} the commission model leaves {following} "
                "to invest: fees would consume the benchmark before it "
                "starts — refusing to invent a size"
            )
        if following == notional:
            break
        notional = following
    else:
        raise BacktestError(
            f"the commission model did not reach a fixed point within "
            f"{_MAX_FEE_STEPS} steps: an approximate benchmark is reported "
            "as a refusal instead"
        )

    quantity = notional / entry_price
    spent_notional = quantity * entry_price
    commission = config.commission.apply(spent_notional)
    steps = 0
    while spent_notional + commission > capital:
        quantity = quantity.next_minus()
        spent_notional = quantity * entry_price
        commission = config.commission.apply(spent_notional)
        steps += 1
        if steps > 1000:
            raise BacktestError(
                "the size could not be brought under the starting capital "
                "within 1000 adjustments: refusing to report a benchmark "
                "that overspends"
            )

    cash_left = capital - spent_notional - commission
    last_close = bars[-1].close
    ending = quantity * last_close + cash_left
    return PassiveBenchmark(
        entry_time=bars[1].timestamp,
        entry_reference=reference,
        entry_price=entry_price,
        quantity=quantity,
        commission=commission,
        cash_left=cash_left,
        last_close=last_close,
        ending_equity=ending,
        net_return=ending / capital - 1,
        bars=len(bars),
        starting_capital=capital,
        assumptions=_ASSUMPTIONS,
    )
