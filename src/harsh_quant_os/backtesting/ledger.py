"""Exact-money position ledger: cash, average cost, realised/unrealised P&L.

``Decimal`` throughout — backtesting-methodology.md §2: "Cash: exact
numerics; no floating-point money". The ledger is the engine's only
mutable state and the strategy never sees it directly; the engine
copies read-only values into each :class:`DecisionContext`.

Accounting model (average cost):

- **Opening or increasing** folds into the running average:
  ``average = (q*average + delta*price) / (q + delta)`` — signed, so
  shorts average correctly. This division runs under the default
  decimal context (28 significant digits): money is decimal-rounded
  only at that depth, never binary-floated.
- **Reducing** realises ``(price - average) * (-delta)`` — one
  expression that is correct for both directions (long sell above the
  average is positive; short cover below it is positive).
- **Crossing through flat** realises the closed portion against the
  average, then re-opens the remainder at the fill price.
- **Commission** is cash-out on every fill and tracked separately, so
  the engine's closing identity holds by construction::

      ending_equity == capital + realised - commission + unrealised

Every mutator validates its inputs first: non-Decimal, non-finite,
zero-delta, non-positive price or negative fee raise
:class:`BacktestError` before a single field changes.
"""

from __future__ import annotations

from decimal import Decimal

from harsh_quant_os.backtesting.errors import BacktestError

__all__ = ["Ledger"]

_ZERO = Decimal(0)


def _money(value: Decimal | int, *, field: str) -> Decimal:
    """Validate an exact money/quantity value: Decimal or int, finite.

    Args:
        value: The raw value.
        field: Name used in error messages.

    Returns:
        The value as ``Decimal``.

    Raises:
        BacktestError: Float/bool input or a non-finite value.
    """
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise BacktestError(
            f"{field} must be a Decimal (exact numerics for money), got "
            f"{type(value).__name__}: {value!r}"
        )
    as_decimal = value if isinstance(value, Decimal) else Decimal(value)
    if not as_decimal.is_finite():
        raise BacktestError(f"{field} must be finite, got {as_decimal}")
    return as_decimal


class Ledger:
    """One instrument's cash and position state, exact.

    A backtest holds at most one position at a time in this engine
    (single instrument, single lot of state): ``quantity`` is the
    signed position, ``average`` its cost basis, ``cash`` everything
    else.

    Attributes:
        property cash: Cash balance after all fills and fees.
        property quantity: Current signed position.
        property average_price: Cost basis of the current position
            (``0`` while flat).
        property realised_pnl: Cumulative realised price P&L,
            commission excluded (fees live in ``total_commission``).
        property total_commission: Cumulative fees paid.
    """

    def __init__(self, starting_capital: Decimal) -> None:
        capital = _money(starting_capital, field="starting_capital")
        if capital <= 0:
            raise BacktestError(f"starting_capital must be positive, got {capital}")
        self._capital = capital
        self._cash = capital
        self._quantity = _ZERO
        self._average = _ZERO
        self._realised = _ZERO
        self._commission = _ZERO

    @property
    def starting_capital(self) -> Decimal:
        return self._capital

    @property
    def cash(self) -> Decimal:
        return self._cash

    @property
    def quantity(self) -> Decimal:
        return self._quantity

    @property
    def average_price(self) -> Decimal:
        return self._average

    @property
    def realised_pnl(self) -> Decimal:
        return self._realised

    @property
    def total_commission(self) -> Decimal:
        return self._commission

    def unrealised_pnl(self, mark: Decimal) -> Decimal:
        """Unrealised P&L of the open position at ``mark`` (0 when flat)."""
        price = _money(mark, field="mark price")
        if price <= 0:
            raise BacktestError(f"mark price must be positive, got {price}")
        return (price - self._average) * self._quantity

    def mark_equity(self, mark: Decimal) -> Decimal:
        """Equity at ``mark``: ``cash + quantity * mark`` (exact)."""
        price = _money(mark, field="mark price")
        if price <= 0:
            raise BacktestError(f"mark price must be positive, got {price}")
        return self._cash + self._quantity * price

    def apply_fill(self, price: Decimal, delta: Decimal, commission: Decimal) -> None:
        """Apply one fill: update cash, position, average and P&L.

        Args:
            price: Fill price (positive, finite, exact).
            delta: Signed quantity change; positive buys, negative
                sells. Zero is refused (the engine skips zero deltas
                before calling).
            commission: Exact non-negative fee charged on this fill.

        Raises:
            BacktestError: Any input invalid — and no field is changed
            when one is (validation precedes mutation).
        """
        fill_price = _money(price, field="fill price")
        quantity_change = _money(delta, field="fill delta")
        fee = _money(commission, field="commission")
        if fill_price <= 0:
            raise BacktestError(f"fill price must be positive, got {fill_price}")
        if quantity_change == 0:
            raise BacktestError("fill delta must be non-zero (nothing traded)")
        if fee < 0:
            raise BacktestError(f"commission must be >= 0, got {fee}")

        current = self._quantity
        same_direction = current == 0 or (quantity_change > 0) == (current > 0)

        if same_direction:
            # Opening from flat, or increasing: fold into the average.
            if current == 0:
                self._average = fill_price
            else:
                self._average = (current * self._average + quantity_change * fill_price) / (
                    current + quantity_change
                )
            self._quantity = current + quantity_change
        elif abs(quantity_change) <= abs(current):
            # Pure reduction: realise the closed portion against the
            # average — (price - average) * (-delta) is correct for a
            # long sell and a short cover alike.
            self._realised += (fill_price - self._average) * (-quantity_change)
            self._quantity = current + quantity_change
            if self._quantity == 0:
                self._average = _ZERO
        else:
            # Crossing through flat: realise the closed portion against
            # the average, then re-open the remainder at this price.
            self._realised += (fill_price - self._average) * current
            self._quantity = current + quantity_change
            self._average = fill_price

        self._cash -= quantity_change * fill_price
        self._cash -= fee
        self._commission += fee
