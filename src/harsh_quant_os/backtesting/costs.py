"""Explicit commission and slippage models — never an implicit zero.

backtesting-methodology.md §2 and backtesting.md §2: costs and
slippage are *named models with parameters*, recorded in the run
manifest, and a missing model is a configuration error rather than a
silent free trade. Slippage is pessimistic by construction: buys fill
above the reference price, sells fill below it.

Both models are Protocols so a future venue-specific model (spread
based, volume participation — backtesting.md §2) plugs in without
touching the engine; the built-ins are frozen dataclasses so the
manifest can serialise them field by field.

Money in, money out: every value is ``Decimal``. Floats are refused at
construction — a slippage rate is a parameter of the experiment, and
experiment parameters do not get binary rounding.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from harsh_quant_os.backtesting.errors import BacktestError

__all__ = ["BpsCommission", "CommissionModel", "FixedBpsSlippage", "SlippageModel"]

_TEN_THOUSAND = Decimal(10_000)


def _exact(value: Decimal | int, *, field: str) -> Decimal:
    """Coerce an exact parameter to Decimal, refusing floats and junk.

    Args:
        value: The raw parameter (``Decimal`` or exact ``int``).
        field: Name used in error messages.

    Returns:
        The value as ``Decimal``.

    Raises:
        BacktestError: A float, bool, string or non-finite value.
    """
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise BacktestError(
            f"{field} must be a Decimal (exact numerics), got {type(value).__name__}: {value!r}"
        )
    as_decimal = value if isinstance(value, Decimal) else Decimal(value)
    if not as_decimal.is_finite():
        raise BacktestError(f"{field} must be finite, got {as_decimal}")
    return as_decimal


@runtime_checkable
class CommissionModel(Protocol):
    """What one fill costs in fees, given its absolute notional."""

    def apply(self, notional: Decimal) -> Decimal:
        """Return the fee for a fill whose |price * quantity| is ``notional``.

        Implementations must charge on the *absolute* notional (short
        sales pay fees too) and return a non-negative exact amount.
        """
        ...


@runtime_checkable
class SlippageModel(Protocol):
    """How far the fill price moves away from the reference price."""

    def apply(self, reference: Decimal, *, buy: bool) -> Decimal:
        """Return the fill price for a buy or sell at ``reference``.

        Implementations must make the fill worse than the reference in
        both directions: a buy above it, a sell below it.
        """
        ...


@dataclass(frozen=True, slots=True)
class BpsCommission:
    """``fee = |notional| * rate_bps / 10_000 + fixed_fee``.

    Attributes:
        rate_bps: Commission in basis points of absolute notional.
        fixed_fee: Flat fee charged on every fill (an explicit zero is
            a recorded choice; omitting the model is not).

    Raises:
        BacktestError: Negative or non-finite components.
    """

    rate_bps: Decimal
    fixed_fee: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        rate = _exact(self.rate_bps, field="commission rate_bps")
        fee = _exact(self.fixed_fee, field="commission fixed_fee")
        if rate < 0:
            raise BacktestError(f"commission rate_bps must be >= 0, got {rate}")
        if fee < 0:
            raise BacktestError(f"commission fixed_fee must be >= 0, got {fee}")
        object.__setattr__(self, "rate_bps", rate)
        object.__setattr__(self, "fixed_fee", fee)

    def apply(self, notional: Decimal) -> Decimal:
        """Fee for a fill: basis points of |notional|, plus the flat fee."""
        exact = _exact(notional, field="notional")
        return exact.copy_abs() * self.rate_bps / _TEN_THOUSAND + self.fixed_fee


@dataclass(frozen=True, slots=True)
class FixedBpsSlippage:
    """A fixed basis-point distance from the reference price.

    ``fill = reference * (1 + bps/10_000)`` for buys and
    ``fill = reference * (1 - bps/10_000)`` for sells — pessimistic in
    both directions, so optimism cannot leak in through the model.

    Attributes:
        bps: Distance from the reference price, in basis points.

    Raises:
        BacktestError: Negative, or >= 10_000 (a sell would reach a
        non-positive price, which is not a price).
    """

    bps: Decimal

    def __post_init__(self) -> None:
        bps = _exact(self.bps, field="slippage bps")
        if bps < 0:
            raise BacktestError(f"slippage bps must be >= 0, got {bps}")
        if bps >= _TEN_THOUSAND:
            raise BacktestError(
                f"slippage bps must be below 10000 so a sell fill stays positive, got {bps}"
            )
        object.__setattr__(self, "bps", bps)

    def apply(self, reference: Decimal, *, buy: bool) -> Decimal:
        """Fill price: above ``reference`` for buys, below it for sells."""
        exact = _exact(reference, field="reference price")
        if exact <= 0:
            raise BacktestError(f"reference price must be positive, got {exact}")
        distance = self.bps / _TEN_THOUSAND
        if buy:
            return exact * (Decimal(1) + distance)
        return exact * (Decimal(1) - distance)
