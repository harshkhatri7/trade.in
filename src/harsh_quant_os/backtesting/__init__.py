"""Deterministic historical simulation: the engine core and its validation.

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
- :mod:`~harsh_quant_os.backtesting.report` — the §5/§6 report:
  limitations first, manifest attached, assumptions separated from
  measured results, plus the cost-sensitivity runs that address the
  cost-optimism row with measurements.
- :mod:`~harsh_quant_os.backtesting.reference` — the reference
  strategy the harness runs: explicit sizing, no hidden defaults.
- :mod:`~harsh_quant_os.backtesting.validation` — Phase 7's data
  separation: chronological train/held-out splits, an access ledger
  that refuses a second held-out touch, and train-slice selection
  that records every variant tried.
- :mod:`~harsh_quant_os.backtesting.walkforward` — Phase 7's
  walk-forward: per-window selection with per-run manifests and an
  aggregated out-of-sample track stored as replayable JSON.

Window coverage (methodology §5's data-side check) is
:func:`~harsh_quant_os.backtesting.data.window_coverage`: missing bars
are counted, never interpolated.

Exit-criteria evidence for this increment lives in
``tests/backtesting/``: hand-computed golden values for the whole
money path, the bounded-history refusal, the final-bar expiry, the
risk-rejection record, bit-identical reruns, manifest reproduction,
metrics restated from the scenario's arithmetic, and the Phase 7
split/ledger/walk-forward refusals.
"""

from __future__ import annotations

from harsh_quant_os.backtesting.costs import (
    BpsCommission,
    CommissionModel,
    FixedBpsSlippage,
    SlippageModel,
)
from harsh_quant_os.backtesting.data import (
    BacktestData,
    WindowCoverage,
    load_backtest_data,
    window_coverage,
)
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
from harsh_quant_os.backtesting.reference import CloseThreshold, parse_decimal
from harsh_quant_os.backtesting.report import (
    DEFAULT_SENSITIVITY_FACTORS,
    CostSensitivityPoint,
    build_report,
    cost_sensitivity,
    wilson_interval,
)
from harsh_quant_os.backtesting.strategy import (
    DecisionContext,
    HistoryView,
    Strategy,
    closes_as_float,
)
from harsh_quant_os.backtesting.validation import (
    ENDING_EQUITY,
    AccessLedger,
    Candidate,
    CandidateRun,
    DataSplit,
    HeldOutEvaluation,
    LedgerEntry,
    OutOfSampleNumbers,
    SelectionObjective,
    SelectionTrace,
    evaluate_held_out,
    select_on_train,
    train_test_split,
)
from harsh_quant_os.backtesting.walkforward import (
    SUMMARY_VERSION,
    OosTrack,
    WalkForwardSummary,
    WalkForwardWindow,
    WindowOutcome,
    walk_forward,
    walk_forward_windows,
)

__all__ = [
    "DEFAULT_SENSITIVITY_FACTORS",
    "ENDING_EQUITY",
    "MANIFEST_VERSION",
    "NEXT_BAR_OPEN",
    "SUMMARY_VERSION",
    "AccessLedger",
    "BacktestConfig",
    "BacktestData",
    "BacktestError",
    "BacktestResult",
    "BpsCommission",
    "Candidate",
    "CandidateRun",
    "CausalityViolation",
    "CloseThreshold",
    "CommissionModel",
    "CostSensitivityPoint",
    "CostStats",
    "DataSplit",
    "DecisionContext",
    "DrawdownStats",
    "EquityPoint",
    "ExposureStats",
    "FixedBpsSlippage",
    "HeldOutEvaluation",
    "HistoryView",
    "Ledger",
    "LedgerEntry",
    "OosTrack",
    "OrderRecord",
    "OrderStatus",
    "OutOfSampleNumbers",
    "ReproductionMismatch",
    "RunMetrics",
    "SelectionObjective",
    "SelectionTrace",
    "SlippageModel",
    "Strategy",
    "TradeStats",
    "VolatilityStats",
    "WalkForwardSummary",
    "WalkForwardWindow",
    "WindowCoverage",
    "WindowOutcome",
    "build_manifest",
    "build_report",
    "closes_as_float",
    "compute_metrics",
    "compute_run_id",
    "cost_sensitivity",
    "evaluate_held_out",
    "load_backtest_data",
    "manifest_from_json",
    "manifest_to_json",
    "parse_decimal",
    "run_backtest",
    "run_from_manifest",
    "select_on_train",
    "train_test_split",
    "walk_forward",
    "walk_forward_windows",
    "wilson_interval",
    "window_coverage",
]
