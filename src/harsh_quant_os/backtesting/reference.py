"""Reference strategies shipped with the harness.

One deliberately simple rule, so that the *machinery* — sequencing,
costs, risk evaluation, manifest, metrics, report — is what a run
exercises, not strategy cleverness. These are illustrations of the
contract, not research findings: their parameters are inputs chosen to
make a run possible, and any report built from them must say so (a
report that presented them as the product of a parameter search would
be claiming a selection process that never happened —
methodology §5's selection-bias row).

:class:`CloseThreshold` holds a fixed size while its entry rule holds
and returns to flat when it does not — an explicit sizing rule with no
hidden defaults (methodology §2 "Sizing: explicit rule; defaults are
visible, not hidden").
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from harsh_quant_os.backtesting.errors import BacktestError
from harsh_quant_os.backtesting.strategy import DecisionContext

__all__ = ["CloseThreshold", "parse_decimal"]


class CloseThreshold:
    """Hold ``target_qty`` units while the entry rule holds; else flat.

    The rule, in full (pure: it reads only the bar and the current
    position, so two runs decide identically):

    - ``close >= entry_above`` -> target the size;
    - ``close <= exit_below`` -> target flat;
    - otherwise (inside the bands) -> hold whatever is held now.

    Args:
        target_qty: Exact position size while the rule holds. Must be a
            finite ``Decimal`` — floats are refused, not rounded.
        entry_above: Enter at or above this close; ``None`` enters
            unconditionally (recorded as ``always``, never omitted).
        exit_below: Return to flat at or below this close; ``None``
            never exits (recorded as ``never``). When both bands are
            given, ``entry_above`` must sit strictly above
            ``exit_below`` or the rule could not be stated.

    Raises:
        BacktestError: Non-Decimal or non-finite parameters, or bands
            that do not describe an entry above an exit.
    """

    name = "close_threshold"

    def __init__(
        self,
        *,
        target_qty: Decimal,
        entry_above: Decimal | None = None,
        exit_below: Decimal | None = None,
    ) -> None:
        for label, value in (
            ("target_qty", target_qty),
            ("entry_above", entry_above),
            ("exit_below", exit_below),
        ):
            if value is None:
                continue
            if not isinstance(value, Decimal):
                raise BacktestError(
                    f"{label} must be a Decimal, got {type(value).__name__} "
                    "(no float reaches a sizing rule)"
                )
            if not value.is_finite():
                raise BacktestError(f"{label} must be finite, got {value}")
        if entry_above is None and exit_below is not None:
            raise BacktestError(
                "exit_below requires an entry_above band: under an "
                "'always' entry the exit could never trigger, so it must "
                "not be recordable as a rule that exists"
            )
        if entry_above is not None and exit_below is not None and entry_above <= exit_below:
            raise BacktestError(
                f"entry_above ({entry_above}) must sit strictly above "
                f"exit_below ({exit_below}): a rule whose entry is at or "
                "below its exit cannot be stated honestly"
            )
        self._target_qty = target_qty
        self._entry_above = entry_above
        self._exit_below = exit_below

    def decide(self, context: DecisionContext) -> Decimal | None:
        """Target position at this bar's close: size, flat, or hold."""
        close = context.bar.close
        if self._entry_above is None or close >= self._entry_above:
            return self._target_qty
        if self._exit_below is not None and close <= self._exit_below:
            return Decimal(0)
        # Inside the bands (or with no exit band): keep the position.
        return context.position

    def describe(self) -> dict[str, str]:
        """Parameters for the run manifest, all strings."""
        entry = "always" if self._entry_above is None else f"close >= {self._entry_above}"
        exit_rule = "never" if self._exit_below is None else f"close <= {self._exit_below}"
        return {"entry": entry, "exit": exit_rule, "target_qty": str(self._target_qty)}


def parse_decimal(text: str, *, label: str) -> Decimal:
    """Parse a CLI-supplied decimal, refusing anything unrepresentable."""
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError) as error:
        raise BacktestError(f"{label} is not a decimal: {text!r}") from error
    if not value.is_finite():
        raise BacktestError(f"{label} must be finite, got {text!r}")
    return value
