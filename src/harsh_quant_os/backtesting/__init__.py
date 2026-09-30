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
- :mod:`~harsh_quant_os.backtesting.manifest` — the §3 run record
  (content-hash ``run_id``, closed-world reconstruction) and its
  byte-identical re-execution check.
- :mod:`~harsh_quant_os.backtesting.metrics` — the §4 metric set with
  its assumptions attached; undefined figures are ``None``, never a
  plausible-looking number.

Exit-criteria evidence for this increment lives in
``tests/backtesting/``: hand-computed golden values for the whole
money path, the bounded-history refusal, the final-bar expiry, the
risk-rejection record, bit-identical reruns, manifest reproduction,
and metrics restated from the scenario's arithmetic.
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
from harsh_quant_os.backtesting.errors import (
    BacktestError,
    CausalityViolation,
    ReproductionMismatch,
)
from harsh_quant_os.backtesting.ledger import Ledger
from harsh_quant_os.backtesting.manifest import (
    MANIFEST_VERSION,
    build_manifest,
    compute_run_id,
    manifest_from_json,
    manifest_to_json,
    run_from_manifest,
)
from harsh_quant_os.backtesting.metrics import (
    CostStats,
    DrawdownStats,
    ExposureStats,
    RunMetrics,
    TradeStats,
    VolatilityStats,
    compute_metrics,
)
from harsh_quant_os.backtesting.strategy import (
    DecisionContext,
    HistoryView,
    Strategy,
    closes_as_float,
)

__all__ = [
    "MANIFEST_VERSION",
    "NEXT_BAR_OPEN",
    "BacktestConfig",
    "BacktestData",
    "BacktestError",
    "BacktestResult",
    "BpsCommission",
    "CausalityViolation",
    "CommissionModel",
    "CostStats",
    "DecisionContext",
    "DrawdownStats",
    "EquityPoint",
    "ExposureStats",
    "FixedBpsSlippage",
    "HistoryView",
    "Ledger",
    "OrderRecord",
    "OrderStatus",
    "ReproductionMismatch",
    "RunMetrics",
    "SlippageModel",
    "Strategy",
    "TradeStats",
    "VolatilityStats",
    "build_manifest",
    "closes_as_float",
    "compute_metrics",
    "compute_run_id",
    "load_backtest_data",
    "manifest_from_json",
    "manifest_to_json",
    "run_backtest",
    "run_from_manifest",
]
