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
- :mod:`~harsh_quant_os.backtesting.sensitivity` — Phase 7's
  parameter-sensitivity surface: the declared grid, every cell,
  adjacency counts, and a replayable JSON that refuses statistics
  which do not follow from its cells.
- :mod:`~harsh_quant_os.backtesting.regimes` — Phase 7's regime
  segmentation: causal labels with declared thresholds, entry-time
  attribution, and the regime-specific flag.
- :mod:`~harsh_quant_os.backtesting.benchmark` — the §2.6 passive
  benchmark: same first fill opportunity, same cost models, same
  marking, assumptions beside the numbers.
- :mod:`~harsh_quant_os.backtesting.null` — the §2.6 shuffled-signal
  null: the same signals re-timed by a recorded seed, with counts
  reported as counts rather than as significance.
- :mod:`~harsh_quant_os.backtesting.deflated` — the §2.5 deflated
  Sharpe: the headline prices how many shots were taken, from a
  recorded count, with its model stated so the arithmetic can be
  checked.
- :mod:`~harsh_quant_os.backtesting.promotion` — the §3 promotion
  workflow: candidates / validated / rejected / archived as a
  closed machine whose gates are checked, not promised — no
  `validated` without held-out, walk-forward, sensitivity and
  critique evidence, a critique from someone other than the author,
  reasons kept on every rejection, and no path to live at all.

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

from harsh_quant_os.backtesting.benchmark import PassiveBenchmark, passive_benchmark
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
from harsh_quant_os.backtesting.deflated import (
    DeflatedSharpe,
    deflated_from_result,
    deflated_sharpe,
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
    RoundTrip,
    RunMetrics,
    TradeRecords,
    TradeStats,
    VolatilityStats,
    compute_metrics,
    trade_records,
)
from harsh_quant_os.backtesting.null import ShuffledNull, shuffle_null
from harsh_quant_os.backtesting.promotion import (
    EVIDENCE_KINDS,
    RECORD_VERSION,
    REQUIRED_FOR_VALIDATED,
    STAGES,
    Evidence,
    PromotionRecord,
    Transition,
    add_evidence,
    archive,
    iter_records,
    load_record,
    promote_to_validated,
    record_from_json,
    record_to_json,
    register,
    reject,
    save_record,
)
from harsh_quant_os.backtesting.reference import CloseThreshold, parse_decimal
from harsh_quant_os.backtesting.regimes import (
    UNDEFINED,
    RegimeLabels,
    RegimeSegment,
    RegimeSplit,
    split_by_regime,
    trend_regimes,
    volatility_regimes,
)
from harsh_quant_os.backtesting.report import (
    DEFAULT_SENSITIVITY_FACTORS,
    CostSensitivityPoint,
    build_report,
    cost_sensitivity,
    wilson_interval,
)
from harsh_quant_os.backtesting.sensitivity import (
    SENSITIVITY_VERSION,
    SensitivityCell,
    SensitivitySurface,
    parameter_sensitivity,
    replay_sensitivity,
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
    replay_walk_forward,
    walk_forward,
    walk_forward_windows,
)

__all__ = [
    "DEFAULT_SENSITIVITY_FACTORS",
    "ENDING_EQUITY",
    "EVIDENCE_KINDS",
    "MANIFEST_VERSION",
    "NEXT_BAR_OPEN",
    "RECORD_VERSION",
    "REQUIRED_FOR_VALIDATED",
    "SENSITIVITY_VERSION",
    "STAGES",
    "SUMMARY_VERSION",
    "UNDEFINED",
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
    "DeflatedSharpe",
    "DrawdownStats",
    "EquityPoint",
    "Evidence",
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
    "PassiveBenchmark",
    "PromotionRecord",
    "RegimeLabels",
    "RegimeSegment",
    "RegimeSplit",
    "ReproductionMismatch",
    "RoundTrip",
    "RunMetrics",
    "SelectionObjective",
    "SelectionTrace",
    "SensitivityCell",
    "SensitivitySurface",
    "ShuffledNull",
    "SlippageModel",
    "Strategy",
    "TradeRecords",
    "TradeStats",
    "Transition",
    "VolatilityStats",
    "WalkForwardSummary",
    "WalkForwardWindow",
    "WindowCoverage",
    "WindowOutcome",
    "add_evidence",
    "archive",
    "build_manifest",
    "build_report",
    "closes_as_float",
    "compute_metrics",
    "compute_run_id",
    "cost_sensitivity",
    "deflated_from_result",
    "deflated_sharpe",
    "evaluate_held_out",
    "iter_records",
    "load_backtest_data",
    "load_record",
    "manifest_from_json",
    "manifest_to_json",
    "parameter_sensitivity",
    "parse_decimal",
    "passive_benchmark",
    "promote_to_validated",
    "record_from_json",
    "record_to_json",
    "register",
    "reject",
    "replay_sensitivity",
    "replay_walk_forward",
    "run_backtest",
    "run_from_manifest",
    "save_record",
    "select_on_train",
    "shuffle_null",
    "split_by_regime",
    "trade_records",
    "train_test_split",
    "trend_regimes",
    "volatility_regimes",
    "walk_forward",
    "walk_forward_windows",
    "wilson_interval",
    "window_coverage",
]
