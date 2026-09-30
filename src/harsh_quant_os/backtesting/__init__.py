"""Deterministic historical simulation — the Phase 6 engine core.

What a backtest is (and is not): a **simulation of the past under
stated assumptions**, evidence about whether an idea survived a
particular history — not a forecast, not a guarantee
(backtesting.md §1). Nothing here talks to a network or a broker; the
only inputs are a version-pinned dataset, a strategy, explicit cost
models and a risk evaluator.

The pieces:

- :mod:`~harsh_quant_os.backtesting.data` — version-pinned bars from
  the content-addressed store, exact ``Decimal`` prices intact.
- :mod:`~harsh_quant_os.backtesting.strategy` — the bounded, pure
  decision contract (no future access, no execution authority).
- :mod:`~harsh_quant_os.backtesting.costs` — explicit commission and
  slippage models; never an implicit zero.
- :mod:`~harsh_quant_os.backtesting.ledger` — exact-money cash,
  average cost, realised/unrealised separation.
- :mod:`~harsh_quant_os.backtesting.engine` — the strict-time loop:
  fill at next bar's open, mark at close, decide; causality asserted
  on every fill; risk evaluated for every order.

Exit-criteria evidence for this increment lives in
``tests/backtesting/``: hand-computed golden values for the whole
money path, the bounded-history refusal, the final-bar expiry, the
risk-rejection record, and bit-identical reruns.
"""

from __future__ import annotations

from harsh_quant_os.backtesting.costs import (
    BpsCommission,
    CommissionModel,
    FixedBpsSlippage,
    SlippageModel,
)
from harsh_quant_os.backtesting.data import BacktestData, load_backtest_data
from harsh_quant_os.backtesting.engine import (
    NEXT_BAR_OPEN,
    BacktestConfig,
    BacktestResult,
    EquityPoint,
    OrderRecord,
    OrderStatus,
    run_backtest,
)
from harsh_quant_os.backtesting.errors import BacktestError, CausalityViolation
from harsh_quant_os.backtesting.ledger import Ledger
from harsh_quant_os.backtesting.strategy import (
    DecisionContext,
    HistoryView,
    Strategy,
    closes_as_float,
)

__all__ = [
    "NEXT_BAR_OPEN",
    "BacktestConfig",
    "BacktestData",
    "BacktestError",
    "BacktestResult",
    "BpsCommission",
    "CausalityViolation",
    "CommissionModel",
    "DecisionContext",
    "EquityPoint",
    "FixedBpsSlippage",
    "HistoryView",
    "Ledger",
    "OrderRecord",
    "OrderStatus",
    "SlippageModel",
    "Strategy",
    "closes_as_float",
    "load_backtest_data",
    "run_backtest",
]
