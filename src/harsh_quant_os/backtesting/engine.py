"""The simulation loop: strict time order, next-bar-open fills, causality.

**Intrabar rule** (fixed and documented — backtesting-methodology.md §2
"Bar ordering: documented and fixed; intrabar assumptions stated
explicitly"), processed for each bar in strictly increasing timestamp
order:

1. **Fill** — an order decided on the previous bar fills at *this*
   bar's **open**, moved by the slippage model, charged the commission
   model.
2. **Mark** — equity is marked at this bar's close.
3. **Decide** — the strategy sees this bar (and everything before it,
   nothing after) and may queue an order for the next bar's open.

Consequences, each deliberate and test-covered:

- A decision never sees its own fill (the fill for bar *t*'s order
  happens on bar *t+1*, before that bar's decision).
- An order decided on the **final** bar cannot fill: it is recorded
  ``EXPIRED`` with a reason, never filled at the last close, never
  silently dropped.
- Gaps are honest: "next bar" means the next *observed* bar, so a gap
  in the data means a distant fill (the report states gap counts).

**Causality is asserted mechanically on every fill**: fill time must be
strictly after the decision's information time (timezone-aware compare;
:class:`BacktestData` already refuses naive and non-increasing stamps,
so this is the engine's own second layer). A violation raises
:class:`CausalityViolation` — it is never logged and continued past.

**Risk evaluation** (backtesting.md §8 criterion 6) is invoked for every
order through the injected evaluator before the order may queue — the
engine owns that step; the strategy has no path around it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from harsh_quant_os.backtesting.costs import CommissionModel, SlippageModel
from harsh_quant_os.backtesting.data import BacktestData
from harsh_quant_os.backtesting.errors import BacktestError, CausalityViolation
from harsh_quant_os.backtesting.ledger import Ledger
from harsh_quant_os.backtesting.strategy import DecisionContext, HistoryView, Strategy
from harsh_quant_os.safety.risk import RiskEvaluator

__all__ = [
    "NEXT_BAR_OPEN",
    "BacktestConfig",
    "BacktestResult",
    "EquityPoint",
    "OrderRecord",
    "OrderStatus",
    "run_backtest",
]

#: The engine's fixed intrabar assumption, recorded in every result and
#: manifest so a reader knows exactly what "when did this fill" means.
NEXT_BAR_OPEN = "next_bar_open"

#: The closing identity is checked to this absolute tolerance: money
#: arithmetic is exact Decimal, but the average-cost division rounds at
#: the decimal context's 28 significant digits, so the check cannot be
#: a naked equality once a position's basis was divided into.
_IDENTITY_TOLERANCE = Decimal("0.000000000001")


class OrderStatus(StrEnum):
    """Lifecycle of one decision the engine acted on."""

    FILLED = "filled"
    EXPIRED = "expired"  # decided on the final bar; no later bar to fill on
    REJECTED = "rejected"  # risk evaluation refused it (reason recorded)


@dataclass(frozen=True, slots=True)
class OrderRecord:
    """One decision, its order, and how — or whether — it executed.

    Attributes:
        decision_time: The bar close whose information created the
            order (the information time).
        target: The strategy's requested position (exact).
        delta: The order quantity, ``target - position`` at decision
            time (exact; non-zero).
        status: See :class:`OrderStatus`.
        fill_time: When it filled, or None (expired/rejected).
        fill_price: Price after slippage, or None (never filled).
        reference_open: The raw bar open the slippage model was applied
            to — so the slippage cost in money is reconstructible.
        commission: Fee charged for this fill (``Decimal(0)`` when it
            did not fill).
        note: Why it expired or was rejected ("" when filled).
    """

    decision_time: datetime
    target: Decimal
    delta: Decimal
    status: OrderStatus
    fill_time: datetime | None
    fill_price: Decimal | None
    reference_open: Decimal | None
    commission: Decimal
    note: str


@dataclass(frozen=True, slots=True)
class EquityPoint:
    """One bar's closing equity mark."""

    time: datetime
    equity: Decimal


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Explicit run inputs — no hidden defaults.

    Capital and both cost models are required fields: there is no
    default slippage of zero and no default capital. Slippage zero is a
    *choice* the manifest can record (``FixedBpsSlippage(Decimal(0))``),
    not something a forgotten field silently becomes.

    Attributes:
        starting_capital: Declared exact capital (> 0).
        commission: The commission model (recorded in the manifest).
        slippage: The slippage model (recorded in the manifest).

    Raises:
        BacktestError: Float/non-positive capital, or missing cost
        models (structural check: the model must provide its method).
    """

    starting_capital: Decimal
    commission: CommissionModel
    slippage: SlippageModel

    def __post_init__(self) -> None:
        # Read through an object-typed local: the declared type is
        # Decimal, but a caller at runtime can pass anything, and the
        # whole point is to refuse it rather than coerce it.
        raw_capital: object = self.starting_capital
        if isinstance(raw_capital, bool) or not isinstance(raw_capital, (Decimal, int)):
            raise BacktestError(
                "starting_capital must be a Decimal (exact numerics for money), got "
                f"{type(raw_capital).__name__}"
            )
        capital = raw_capital if isinstance(raw_capital, Decimal) else Decimal(raw_capital)
        if not capital.is_finite():
            raise BacktestError(f"starting_capital must be finite, got {capital}")
        if capital <= 0:
            raise BacktestError(f"starting_capital must be positive, got {capital}")
        object.__setattr__(self, "starting_capital", capital)
        if not isinstance(self.commission, CommissionModel):
            raise BacktestError(
                "commission must be an explicit model providing apply(notional) — "
                "a backtest never defaults its costs to zero (methodology §2)"
            )
        if not isinstance(self.slippage, SlippageModel):
            raise BacktestError(
                "slippage must be an explicit named model providing "
                "apply(reference, buy=...) — never an implicit zero (methodology §2)"
            )


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Everything one run produced, exact and immutable.

    The numbers carry their own provenance: dataset identity and
    version, strategy name and sorted parameters, and the intrabar rule
    the fills followed — the fields a manifest needs (backtesting.md
    §4) without yet being one (the manifest layer is increment 3).

    Attributes:
        dataset_id / dataset_version: The pinned input (content-addressed
            SHA-256, recomputed by the loader).
        strategy_name / strategy_parameters: From the strategy, sorted
            by key so construction order cannot move the bytes.
        intrabar_rule: Always ``"next_bar_open"`` in this engine.
        starting_capital: The declared capital.
        orders: Every non-zero-delta decision, in decision order.
        equity_curve: One mark per bar close, in time order.
        ending_cash / ending_quantity / ending_equity / ending_unrealised:
            Final ledger snapshot (realised is separate — §2 "Realised
            and unrealised P&L are always separated").
        realised_pnl: Cumulative realised price P&L (fees excluded).
        total_commission: Cumulative fees paid.
    """

    dataset_id: str
    dataset_version: str
    strategy_name: str
    strategy_parameters: tuple[tuple[str, str], ...]
    intrabar_rule: str
    starting_capital: Decimal
    orders: tuple[OrderRecord, ...]
    equity_curve: tuple[EquityPoint, ...]
    ending_cash: Decimal
    ending_quantity: Decimal
    ending_equity: Decimal
    ending_unrealised: Decimal
    realised_pnl: Decimal
    total_commission: Decimal

    @property
    def filled(self) -> tuple[OrderRecord, ...]:
        """Orders that actually executed, in decision order."""
        return tuple(order for order in self.orders if order.status is OrderStatus.FILLED)

    @property
    def expired(self) -> tuple[OrderRecord, ...]:
        """Orders that could not fill (final bar, no later bar exists)."""
        return tuple(order for order in self.orders if order.status is OrderStatus.EXPIRED)

    @property
    def rejected(self) -> tuple[OrderRecord, ...]:
        """Orders the risk evaluation refused (reason recorded per order)."""
        return tuple(order for order in self.orders if order.status is OrderStatus.REJECTED)


@dataclass(frozen=True, slots=True)
class _PendingOrder:
    """An approved order waiting for the next bar's open."""

    decision_time: datetime
    target: Decimal
    delta: Decimal


def _coerce_target(target: Decimal | int | None) -> Decimal | None:
    """Validate a strategy's return: Decimal/int quantity, or None.

    Raises:
        BacktestError: Floats and booleans (money is not binary), or
        non-finite quantities.
    """
    if target is None:
        return None
    if isinstance(target, bool) or not isinstance(target, (Decimal, int)):
        raise BacktestError(
            "a strategy target position must be Decimal, int or None; got "
            f"{type(target).__name__}: {target!r} (exact numerics for money)"
        )
    as_decimal = target if isinstance(target, Decimal) else Decimal(target)
    if not as_decimal.is_finite():
        raise BacktestError(f"a target position must be finite, got {as_decimal}")
    return as_decimal


def _describe(strategy: Strategy) -> tuple[tuple[str, str], ...]:
    """Freeze ``strategy.describe()`` for the record, canonically.

    Raises:
        BacktestError: Non-string keys/values (manifests are JSON), or
        an empty strategy name.
    """
    name = strategy.name
    if not isinstance(name, str) or not name.strip():
        raise BacktestError(f"strategy.name must be a non-empty string, got {name!r}")
    raw = strategy.describe()
    pairs: list[tuple[str, str]] = []
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise BacktestError(
                "strategy.describe() must map strings to strings (manifests are "
                f"canonical JSON), got {key!r}: {value!r}"
            )
        pairs.append((key, value))
    return tuple(sorted(pairs))


def run_backtest(
    data: BacktestData,
    strategy: Strategy,
    config: BacktestConfig,
    *,
    risk: RiskEvaluator,
) -> BacktestResult:
    """Run one deterministic historical simulation.

    Args:
        data: Version-pinned bars (validated, strictly increasing).
        strategy: The decision rule (see :class:`Strategy`).
        config: Explicit capital and cost models.
        risk: The pre-trade risk evaluator; consulted for every order
            (backtesting.md §8 criterion 6 — required keyword, no
            permissive default).

    Returns:
        The immutable result: orders, equity curve, final snapshot.

    Raises:
        BacktestError: Fewer than two bars (nothing can fill), a
        contract violation (bad target, bad describe), or a violated
        closing identity.
        CausalityViolation: A fill that does not strictly follow its
        decision's information time.
    """
    if len(data.bars) < 2:
        raise BacktestError(
            f"a backtest needs at least two bars (one to decide on, the next to "
            f"fill on); got {len(data.bars)}"
        )

    parameters = _describe(strategy)
    ledger = Ledger(config.starting_capital)
    orders: list[OrderRecord] = []
    curve: list[EquityPoint] = []
    pending: _PendingOrder | None = None
    last_index = len(data.bars) - 1

    for index, bar in enumerate(data.bars):
        # 1. Fill what the previous bar decided, at this bar's open.
        if pending is not None:
            if not (bar.timestamp > pending.decision_time):
                raise CausalityViolation(
                    f"fill at {bar.timestamp.isoformat()} does not strictly follow "
                    f"the decision at {pending.decision_time.isoformat()}: an order "
                    "may only fill after the information that created it "
                    "(backtesting.md section 2, Causality)"
                )
            buy = pending.delta > 0
            fill_price = config.slippage.apply(bar.open, buy=buy)
            fee = config.commission.apply(pending.delta * fill_price)
            ledger.apply_fill(fill_price, pending.delta, fee)
            orders.append(
                OrderRecord(
                    decision_time=pending.decision_time,
                    target=pending.target,
                    delta=pending.delta,
                    status=OrderStatus.FILLED,
                    fill_time=bar.timestamp,
                    fill_price=fill_price,
                    reference_open=bar.open,
                    commission=fee,
                    note="",
                )
            )
            pending = None

        # 2. Mark equity at this bar's close.
        marked = ledger.mark_equity(bar.close)
        curve.append(EquityPoint(time=bar.timestamp, equity=marked))

        # 3. Decide: bounded history, current ledger state, close mark.
        context = DecisionContext(
            history=HistoryView(data.bars, index + 1),
            bar=bar,
            position=ledger.quantity,
            cash=ledger.cash,
            equity=marked,
        )
        target = _coerce_target(strategy.decide(context))
        if target is None:
            continue
        delta = target - ledger.quantity
        if delta == 0:
            continue

        if index == last_index:
            orders.append(
                OrderRecord(
                    decision_time=bar.timestamp,
                    target=target,
                    delta=delta,
                    status=OrderStatus.EXPIRED,
                    fill_time=None,
                    fill_price=None,
                    reference_open=None,
                    commission=Decimal(0),
                    note="decided on the final bar; no later bar exists to fill on",
                )
            )
            continue

        # Risk evaluation before the order may queue — the engine calls
        # it for every order; the strategy has no path around it.
        verdict = risk.evaluate(
            decision_time=bar.timestamp,
            delta=delta,
            price=bar.close,
            equity=marked,
        )
        if not verdict.approved:
            orders.append(
                OrderRecord(
                    decision_time=bar.timestamp,
                    target=target,
                    delta=delta,
                    status=OrderStatus.REJECTED,
                    fill_time=None,
                    fill_price=None,
                    reference_open=None,
                    commission=Decimal(0),
                    note=verdict.reason,
                )
            )
            continue

        pending = _PendingOrder(decision_time=bar.timestamp, target=target, delta=delta)

    # Closing identity: capital + realised - fees + unrealised == equity.
    # Exact for division-free bases; average-cost division rounds at the
    # decimal context depth, hence the stated tolerance.
    last_close = data.bars[-1].close
    ending_equity = ledger.mark_equity(last_close)
    expected = (
        config.starting_capital
        + ledger.realised_pnl
        - ledger.total_commission
        + ledger.unrealised_pnl(last_close)
    )
    if abs(ending_equity - expected) > _IDENTITY_TOLERANCE:
        raise BacktestError(
            "internal invariant violated: ending equity "
            f"{ending_equity} != capital + realised - commission + unrealised "
            f"{expected}"
        )

    return BacktestResult(
        dataset_id=data.dataset_id,
        dataset_version=data.version,
        strategy_name=strategy.name,
        strategy_parameters=parameters,
        intrabar_rule=NEXT_BAR_OPEN,
        starting_capital=config.starting_capital,
        orders=tuple(orders),
        equity_curve=tuple(curve),
        ending_cash=ledger.cash,
        ending_quantity=ledger.quantity,
        ending_equity=ending_equity,
        ending_unrealised=ledger.unrealised_pnl(last_close),
        realised_pnl=ledger.realised_pnl,
        total_commission=ledger.total_commission,
    )
