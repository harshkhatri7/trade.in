"""Report generation: the same run, told honestly.

Two documents govern this module and every string it emits:

- **backtesting-methodology.md §6 (reporting rules):** limitations
  first, not last; measured results separated from assumptions;
  conditional language ("under these assumptions", "in this sample");
  never present a backtest as evidence of future performance; attach
  the manifest so the reader can reproduce the run.
- **backtesting.md §5 (reporting rules):** distinguish in-sample from
  out-of-sample; show the number of trades and call out small samples;
  show drawdown and time under water alongside return; list
  assumptions and known biases; carry the standard caveat that past
  performance is not indicative of future results.

Design commitments:

- :func:`build_report` is **pure**: it renders numbers already
  recorded in the result, manifest, metrics and coverage record. It
  cannot compute a new statistic, so it cannot invent one.
- Everything undefined reads as *not defined* with the reason beside
  it (methodology §4: a metric without its assumptions is not
  reported), never as a plausible zero.
- The only interval in the report is the Wilson score interval for the
  hit rate: a closed-form, deterministic calculation (the engine
  consumes no randomness, so no seeded bootstrap is run — stated as a
  limitation instead of quietly skipped).
- :func:`cost_sensitivity` re-runs the same strategy at scaled costs,
  addressing methodology §5's "cost optimism" row with measurements
  rather than assurance. Each variant run gets a **fresh** risk
  evaluator (evaluators are per-run, like strategies).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from harsh_quant_os.backtesting.costs import BpsCommission, FixedBpsSlippage
from harsh_quant_os.backtesting.data import BacktestData, WindowCoverage
from harsh_quant_os.backtesting.deflated import DeflatedSharpe
from harsh_quant_os.backtesting.engine import BacktestConfig, BacktestResult, run_backtest
from harsh_quant_os.backtesting.errors import BacktestError
from harsh_quant_os.backtesting.metrics import RunMetrics
from harsh_quant_os.backtesting.strategy import Strategy
from harsh_quant_os.safety.risk import RiskEvaluator

__all__ = [
    "DEFAULT_SENSITIVITY_FACTORS",
    "CostSensitivityPoint",
    "build_report",
    "cost_sensitivity",
    "wilson_interval",
]

#: Cost multipliers the sensitivity table runs by default: half, as
#: recorded, and double. Stated in the report, never implicit.
DEFAULT_SENSITIVITY_FACTORS: tuple[Decimal, ...] = (
    Decimal("0.5"),
    Decimal(1),
    Decimal(2),
)

#: Trade-count threshold below which methodology §5's "small samples"
#: row applies. The report names this number where it uses it.
SMALL_SAMPLE_TRADE_THRESHOLD = 30

#: Sample spans shorter than this many years get an explicit warning
#: that annualisation is extrapolating them across a full year.
SHORT_SAMPLE_YEARS = Decimal("0.08")

#: Two-sided 95% normal quantile for the Wilson interval — a stated
#: constant, not a fitted one.
_WILSON_Z_95 = Decimal("1.959963984540054")


# ---------------------------------------------------------------------------
# Cost sensitivity (methodology §5: cost optimism)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CostSensitivityPoint:
    """One scaled-cost re-run of the same strategy on the same bars.

    Attributes:
        factor: What commission and slippage were multiplied by.
        ending_equity: The run's ending equity under those costs.
        total_commission: Fees paid under those costs.
        filled: Orders that filled under those costs.
    """

    factor: Decimal
    ending_equity: Decimal
    total_commission: Decimal
    filled: int


def _scaled_config(config: BacktestConfig, factor: Decimal) -> BacktestConfig:
    """The same run configuration with both cost models scaled."""
    if not isinstance(config.commission, BpsCommission):
        raise BacktestError(
            "cost sensitivity can only scale a bps_commission, got "
            f"{type(config.commission).__name__}: refusing to report a "
            "sensitivity it cannot compute"
        )
    if not isinstance(config.slippage, FixedBpsSlippage):
        raise BacktestError(
            "cost sensitivity can only scale a fixed_bps_slippage, got "
            f"{type(config.slippage).__name__}: refusing to report a "
            "sensitivity it cannot compute"
        )
    return BacktestConfig(
        starting_capital=config.starting_capital,
        commission=BpsCommission(
            rate_bps=config.commission.rate_bps * factor,
            fixed_fee=config.commission.fixed_fee * factor,
        ),
        slippage=FixedBpsSlippage(bps=config.slippage.bps * factor),
    )


def cost_sensitivity(
    data: BacktestData,
    strategy: Strategy,
    config: BacktestConfig,
    *,
    risk_factory: Callable[[], RiskEvaluator],
    factors: Sequence[Decimal] = DEFAULT_SENSITIVITY_FACTORS,
) -> tuple[CostSensitivityPoint, ...]:
    """Re-run the same strategy with scaled costs, one run per factor.

    Each run builds its evaluator through ``risk_factory`` so every
    variant starts with fresh day-start state — an evaluator reused
    across runs would carry refusals from one variant into the next.

    Args:
        data: The pinned bars (identical across variants).
        strategy: A fresh instance per call is the caller's choice;
            the rule must be the same one the report's base run used.
        config: Base configuration; its two cost models are scaled.
        risk_factory: Builds a fresh evaluator per variant run.
        factors: Cost multipliers; defaults to half, one and two.

    Returns:
        One point per factor, in the order given.

    Raises:
        BacktestError: A cost model this build cannot scale (the
            report must not show a sensitivity it did not compute).
    """
    points: list[CostSensitivityPoint] = []
    for factor in factors:
        run = run_backtest(
            data,
            strategy,
            _scaled_config(config, factor),
            risk=risk_factory(),
        )
        points.append(
            CostSensitivityPoint(
                factor=factor,
                ending_equity=run.ending_equity,
                total_commission=run.total_commission,
                filled=len(run.filled),
            )
        )
    return tuple(points)


# ---------------------------------------------------------------------------
# Uncertainty (deterministic, closed form)
# ---------------------------------------------------------------------------


def wilson_interval(
    successes: int,
    trials: int,
    *,
    z: Decimal = _WILSON_Z_95,
) -> tuple[Decimal, Decimal] | None:
    """Wilson score interval for a proportion (two-sided, default 95%).

    Chosen because it is exactly computable in ``Decimal`` — the report
    needs an interval, and the engine deliberately has no randomness
    with which to bootstrap one. The independence assumption is the
    model's, and the report states it beside the numbers.

    Args:
        successes: Count of hits (e.g. winning round trips).
        trials: Count of attempts (e.g. completed round trips).
        z: Two-sided normal quantile.

    Returns:
        ``(lower, upper)`` exact bounds, or ``None`` when there were no
        trials — no attempts means no interval, not a zero-width one.

    Raises:
        BacktestError: Counts outside ``0..trials``.
    """
    if trials <= 0:
        return None
    if successes < 0 or successes > trials:
        raise BacktestError(
            f"wilson_interval needs 0 <= successes <= trials, got {successes} of {trials}"
        )
    count = Decimal(trials)
    proportion = Decimal(successes) / count
    z_squared = z * z
    denominator = Decimal(1) + z_squared / count
    centre = (proportion + z_squared / (2 * count)) / denominator
    variance_term = (proportion * (1 - proportion) + z_squared / (4 * count)) / count
    margin = z * variance_term.sqrt() / denominator
    return (centre - margin, centre + margin)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _cell(value: object) -> str:
    """A manifest cell: recorded values verbatim, absence named."""
    if value is None:
        return "not recorded"
    return str(value)


def _record_line(record: Mapping[str, object]) -> str:
    """``type=x a=y`` for a manifest's model/limits record."""
    return " ".join(f"{key}={value}" for key, value in sorted(record.items()))


def _as_record(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, dict) else None


def _decimal_or_not(value: Decimal | None, note: str = "") -> str:
    if value is None:
        return f"not defined{f' ({note})' if note else ''}"
    return str(value)


def _duration_text(span: object) -> str:
    return str(span)


def _mapping_text(value: object, *, fallback: str) -> str:
    """A manifest's mapping/list value, rendered for a cell."""
    if isinstance(value, dict):
        return str(dict(value))
    if isinstance(value, list):
        return str(list(value))
    return fallback


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def build_report(
    result: BacktestResult,
    *,
    manifest: Mapping[str, object],
    metrics: RunMetrics,
    coverage: WindowCoverage,
    sensitivity: Sequence[CostSensitivityPoint] | None = None,
    strategy_note: str | None = None,
    deflated: DeflatedSharpe | None = None,
) -> str:
    """Render one run as a markdown report, limitations first.

    Args:
        result: The recorded run.
        manifest: Its §3 manifest (typically from
            :func:`~harsh_quant_os.backtesting.manifest.build_manifest`).
        metrics: Its §4 metric set with assumptions.
        coverage: Window-coverage record for the dataset.
        sensitivity: Pre-computed cost-sensitivity points, or ``None``
            (the report says it was not computed — it never implies a
            check that did not run).
        strategy_note: Extra honest context about the strategy (e.g.
            that its parameters are illustrative), rendered as a
            limitation.
        deflated: The pre-computed §2.5 multiple-testing adjustment
            (from :func:`~harsh_quant_os.backtesting.deflated.deflated_from_result`
            with the recorded shot count), or ``None`` — the report
            then says the variant count was not recorded, exactly as
            before. A count is never invented: only what was computed
            and passed in is rendered.

    Returns:
        Markdown text. No line of it asserts anything about outcomes
        outside this sample.
    """
    dataset_record = _as_record(manifest.get("dataset")) or {}
    strategy_record = _as_record(manifest.get("strategy")) or {}
    commission_record = _as_record(manifest.get("commission")) or {}
    slippage_record = _as_record(manifest.get("slippage")) or {}
    risk_limits_record = _as_record(manifest.get("risk_limits"))
    universe_record = _as_record(manifest.get("universe")) or {}
    results_record = _as_record(manifest.get("results")) or {}

    run_id = _cell(manifest.get("run_id"))
    dataset_id = _cell(dataset_record.get("id"))
    dataset_version = _cell(dataset_record.get("version"))
    period = f"{_cell(dataset_record.get('start'))} to {_cell(dataset_record.get('end'))}"
    bars = dataset_record.get("bars", result.equity_curve and len(result.equity_curve))

    # ---- limitations, computed from the record before any figure -----
    limitations: list[str] = [
        (
            'This is a simulation of past data. It answers "what would have '
            'happened under these assumptions, in this sample" - never "what '
            'will happen".'
        ),
        (
            "One window, entirely in-sample: no train/test split or "
            "out-of-sample segment was run for this report, so every figure "
            "below is in-sample evidence only."
        ),
    ]
    if metrics.sample_years < SHORT_SAMPLE_YEARS:
        limitations.append(
            f"The sample spans {metrics.sample_years!s} years (about "
            f"{_duration_text(result.equity_curve[-1].time - result.equity_curve[0].time)}). "
            "Annualised figures extrapolate that span across a full year; they "
            "are arithmetic on this window, not an expectation of any future "
            "window."
        )
    trade_count = metrics.trades.round_trips
    if trade_count < SMALL_SAMPLE_TRADE_THRESHOLD:
        limitations.append(
            f"{trade_count} completed round trips - below the "
            f"{SMALL_SAMPLE_TRADE_THRESHOLD}-trade threshold this methodology "
            "calls small. Per-trade statistics rest on little evidence and "
            "another window would likely differ."
        )
    limitations.append(
        "No bootstrap or resampled interval is shown: the engine consumes no "
        "randomness, so none was run. The Uncertainty section gives a Wilson "
        "score interval for the hit rate instead (it assumes independent "
        "trials)."
    )
    if deflated is None:
        limitations.append(
            "The number of strategy variants tried before this run was not "
            "recorded, so its multiple-testing context is unavailable "
            "(methodology §5, selection bias)."
        )
    else:
        limitations.append(
            f"Multiple-testing: {deflated.trials} variant(s) were tried "
            f"before this run and the count was recorded (anti-overfitting "
            f"§2.5), so the deflated Sharpe below prices it. The deflation "
            f"is a model result — iid normal shots and a complete count — "
            f"not a property of this sample."
        )
    limitations.append(
        "Borrow, financing and funding are not modelled: costs are the "
        "recorded commission and slippage only."
    )
    limitations.append(
        f"Single instrument ({result.symbol}): universe membership is this "
        "dataset's one symbol for its full span, so multi-instrument "
        "survivorship checks have nothing to reduce - they need "
        "multi-instrument support, which is not implemented."
    )
    if coverage.missing_bars is None:
        limitations.append(
            f"Window coverage: gap analysis is not computable for timeframe "
            f"'{coverage.timeframe}' (no fixed bar length) - stated here "
            "rather than estimated."
        )
    elif coverage.missing_bars > 0:
        limitations.append(
            f"Window coverage: {coverage.missing_bars} bars are missing across "
            f"{coverage.gap_intervals} gap interval(s) in the stored dataset; "
            "they are counted here, never interpolated."
        )
    else:
        limitations.append(
            "Window coverage: the bars are contiguous across their span at the "
            "nominal timeframe (checked, not assumed)."
        )
    if sensitivity is None:
        limitations.append(
            "Cost sensitivity was not computed for this report; the recorded "
            "costs are the only costs shown."
        )
    else:
        factors_text = ", ".join(f"{point.factor}x" for point in sensitivity)
        limitations.append(
            f"Cost sensitivity covers only the factors {factors_text} scaled "
            "together; other cost shapes are not explored here."
        )
    if strategy_note:
        limitations.append(strategy_note)

    limitation_lines = "\n".join(
        f"{index}. {text}" for index, text in enumerate(limitations, start=1)
    )

    # ---- caveat -------------------------------------------------------
    caveat = (
        "> Under these assumptions, in this sample, the figures below describe "
        "what would have happened to this dataset's bars - nothing more. "
        "Past performance is not indicative of future results. A backtest is "
        "evidence about the past, not a promise about the future."
    )

    # ---- manifest -----------------------------------------------------
    git_value = manifest.get("git_sha")
    git_cell = (
        str(git_value)
        if git_value is not None
        else "null (git unavailable at run time; never invented)"
    )
    seed_value = manifest.get("seed")
    seed_cell = (
        str(seed_value) if seed_value is not None else "null (this engine consumes no randomness)"
    )
    manifest_table = "\n".join(
        [
            "| field | value |",
            "| --- | --- |",
            f"| run id | `{run_id}` |",
            f"| git sha | {git_cell} |",
            f"| engine version | {_cell(manifest.get('engine_version'))} |",
            f"| dataset | `{dataset_id}` version `{dataset_version}` |",
            f"| period | {period} ({bars} bars, {_cell(manifest.get('timezone'))}) |",
            f"| strategy | `{_cell(strategy_record.get('name'))}` "
            f"{_mapping_text(strategy_record.get('parameters'), fallback='{}')} |",
            f"| starting capital | {_cell(manifest.get('capital'))} |",
            f"| commission | {_record_line(commission_record)} |",
            f"| slippage | {_record_line(slippage_record)} |",
            f"| intrabar rule | {_cell(manifest.get('intrabar_rule'))} |",
            f"| risk limits | "
            f"{_record_line(risk_limits_record) if risk_limits_record else 'not recorded'} |",
            f"| seed | {seed_cell} |",
        ]
    )
    manifest_json = json.dumps(dict(manifest), indent=2, sort_keys=True, ensure_ascii=True)

    # ---- assumptions (not measurements) -------------------------------
    assumptions_lines = [
        f"- **Cost model:** {_record_line(commission_record)}",
        f"- **Slippage model:** {_record_line(slippage_record)}",
        f"- **Starting capital:** {_cell(manifest.get('capital'))} (exact "
        "decimal; the engine has no floating-point money)",
        f"- **Intrabar rule:** {_cell(manifest.get('intrabar_rule'))} - fills "
        "happen at the next bar's open after the decision, never inside the "
        "bar that produced it",
        f"- **Risk limits:** "
        f"{_record_line(risk_limits_record) if risk_limits_record else 'not recorded'}"
        " - evaluated for every simulated order",
        f"- **Strategy inputs:** "
        f"{_mapping_text(strategy_record.get('parameters'), fallback='{}')}"
        f" - {strategy_note or 'reference parameters, not the output of a parameter search'}",
        "- **Metric conventions:**",
    ]
    assumptions_lines.extend(f"  - {key}: {value}" for key, value in metrics.assumptions)

    # ---- measured results ---------------------------------------------
    drawdown = metrics.drawdown
    if drawdown.peak_time is None:
        drawdown_text = "none (the equity curve never fell below a prior peak)"
    else:
        recovery = "recovered" if drawdown.recovered else "unrecovered at sample end"
        under_water = str(drawdown.time_under_water) if drawdown.time_under_water else "-"
        drawdown_text = (
            f"{drawdown.max_drawdown} ({drawdown.max_drawdown_amount}) "
            f"peak {_cell(drawdown.peak_time.isoformat())} to trough "
            f"{_cell(drawdown.trough_time.isoformat() if drawdown.trough_time else None)}; "
            f"under water {under_water} ({recovery})"
        )

    trades = metrics.trades
    if trades.round_trips == 0:
        trade_line = "0 completed round trips"
    else:
        trade_line = (
            f"{trades.round_trips} completed round trips; "
            f"{trades.wins} win(s), {trades.losses} loss(es), "
            f"{trades.breakeven} breakeven; "
            f"hit rate {_decimal_or_not(trades.hit_rate)}; "
            f"median holding {_cell(trades.median_holding)}"
        )
    if trades.round_trips == 0:
        win_sizes = "no winning round trips"
        loss_sizes = "no losing round trips"
    else:
        win_sizes = (
            "no winning round trips"
            if trades.median_win is None
            else (
                f"median {trades.median_win}, mean {trades.mean_win}, "
                f"min {trades.min_win}, max {trades.max_win}"
            )
        )
        loss_sizes = (
            "no losing round trips"
            if trades.median_loss is None
            else (
                f"median {trades.median_loss}, mean {trades.mean_loss}, "
                f"min {trades.min_loss}, max {trades.max_loss}"
            )
        )

    measured_table = "\n".join(
        [
            "| measure | value |",
            "| --- | --- |",
            f"| starting equity | {_cell(results_record.get('starting_capital'))} |",
            f"| ending equity | {_cell(results_record.get('ending_equity'))} |",
            f"| ending cash / position | "
            f"{_cell(results_record.get('ending_cash'))} / "
            f"{_cell(results_record.get('ending_quantity'))} |",
            f"| realised P&L | {_cell(results_record.get('realised_pnl'))} |",
            f"| total return | {metrics.total_return} |",
            f"| annualised return | {metrics.annualised_return} "
            f"(over {metrics.sample_years} years of elapsed time) |",
            f"| volatility (annualised) | "
            f"{_decimal_or_not(metrics.volatility.annualised, metrics.volatility.note)} |",
            f"| Sharpe (annualised, rf=0) | "
            f"{_decimal_or_not(metrics.volatility.sharpe, metrics.volatility.note)} |",
            f"| maximum drawdown | {drawdown_text} |",
            f"| trades | {trade_line} |",
            f"| winning sizes | {win_sizes} |",
            f"| losing sizes | {loss_sizes} |",
            f"| open position at sample end | {trades.open_position_at_end} |",
            f"| commission paid | {metrics.costs.commission} |",
            f"| slippage paid | {metrics.costs.slippage} |",
            f"| total costs | {metrics.costs.total} |",
            f"| turnover | {metrics.costs.turnover} |",
            f"| exposure, gross (share of bars in position) | {metrics.exposure.gross_time} |",
            f"| exposure, net (position value vs equity) | {metrics.exposure.net_equity_ratio} |",
            f"| peak concentration | {metrics.exposure.peak_concentration} |",
        ]
    )

    # ---- uncertainty ---------------------------------------------------
    interval = wilson_interval(trades.wins, trades.round_trips)
    if interval is None:
        interval_line = (
            "No completed round trips, so no interval - absence of attempts is "
            "not a zero-width interval."
        )
    else:
        interval_line = (
            f"Hit rate {trades.hit_rate} has a Wilson 95% interval of "
            f"[{interval[0]}, {interval[1]}] over {trades.round_trips} trial(s). "
            "The interval assumes independent, identically distributed trials "
            "- an assumption of the model, not a property of this sample."
        )
    small_sample_line = (
        f"Trades: {trades.round_trips} against the "
        f"{SMALL_SAMPLE_TRADE_THRESHOLD}-trade threshold - "
        + (
            "small sample, wide uncertainty."
            if trades.round_trips < SMALL_SAMPLE_TRADE_THRESHOLD
            else "above the small-sample threshold."
        )
        + f" Bars: {bars}."
    )

    # ---- multiple-testing adjustment (anti-overfitting §2.5) -----------
    if deflated is None:
        variants_line = "not recorded for this run."
        multiple_testing_text = ""
    else:
        variants_line = f"{deflated.trials} (recorded - see the multiple-testing adjustment below)."
        multiple_testing_text = (
            "## Multiple-testing adjustment (anti-overfitting §2.5)\n\n"
            f"{deflated.note}\n\n"
            "| figure | value |\n"
            "| --- | --- |\n"
            f"| variants tried ({deflated.shots_text}) | {deflated.trials} |\n"
            f"| periods the estimate stands on | {deflated.periods} |\n"
            f"| per-period Sharpe (observed) | {deflated.sharpe} |\n"
            f"| best-of-{deflated.trials} null expectation (SR0) | "
            f"{deflated.null_expected_max} |\n"
            f"| Sharpe estimator variance V[SR] | {deflated.sr_variance} |\n"
            f"| return skewness (population) | {deflated.skewness} |\n"
            f"| return kurtosis (population, 3 = normal) | {deflated.kurtosis} |\n"
            f"| deflated Sharpe | {deflated.deflated} |\n\n"
        )

    # ---- cost sensitivity ---------------------------------------------
    if sensitivity is None:
        sensitivity_text = "_Cost sensitivity was not computed for this report_ (see limitations)."
    else:
        sensitivity_rows = "\n".join(
            f"| {point.factor}x | {point.ending_equity} | "
            f"{point.total_commission} | {point.filled} |"
            for point in sensitivity
        )
        sensitivity_text = (
            "The same strategy and bars re-run with commission and slippage "
            "scaled together:\n\n"
            "| cost factor | ending equity | commission | filled orders |\n"
            "| --- | --- | --- | --- |\n"
            f"{sensitivity_rows}"
        )

    # ---- coverage and universe ----------------------------------------
    if coverage.nominal_seconds is None:
        coverage_line = (
            f"Window {coverage.start.isoformat()} to {coverage.end.isoformat()}: "
            f"{coverage.actual_bars} bars at '{coverage.timeframe}'; gap "
            "analysis not computable for a timeframe with no fixed length - "
            "stated, not estimated."
        )
    else:
        missing = coverage.missing_bars
        status = "complete" if coverage.is_complete else "incomplete"
        coverage_line = (
            f"Window {coverage.start.isoformat()} to {coverage.end.isoformat()}: "
            f"{coverage.actual_bars} bars at '{coverage.timeframe}' "
            f"(nominal {coverage.nominal_seconds}s); expected "
            f"{coverage.expected_bars} for the span, {missing} missing across "
            f"{coverage.gap_intervals} gap interval(s), "
            f"{coverage.irregular_intervals} irregular interval(s) - coverage "
            f"{status}."
        )
    universe_line = (
        f"Universe: {_mapping_text(universe_record.get('instruments'), fallback='[]')} "
        f"as of "
        f"{_cell(universe_record.get('as_of'))} - one instrument pinned to "
        "this dataset for its full span; membership does not change inside "
        "the window, so there is no membership survivorship to distort "
        "(multi-instrument membership is not implemented)."
    )

    # ---- assemble --------------------------------------------------------
    return f"""# Backtest report - {_cell(strategy_record.get("name"))} on {result.symbol} ({result.timeframe})

run id `{run_id}` - dataset `{dataset_id}` version `{dataset_version}` - {bars} bars, {period}

## Limitations (read first)

{limitation_lines}

## Caveat

{caveat}

## Run manifest

Attached so the run can be reproduced (methodology §3). The canonical
byte form of the manifest is what reproduces it; the pretty form below
is the same data.

{manifest_table}

```json
{manifest_json}
```

## Assumptions (these are not measurements)

{chr(10).join(assumptions_lines)}

## Measured results (this sample only)

{measured_table}

## Uncertainty

- {interval_line}
- {small_sample_line}
- Variants tried: {variants_line}

{multiple_testing_text}## Cost sensitivity

{sensitivity_text}

## Coverage and universe

- {coverage_line}
- {universe_line}

## Reproducing this run

Load the dataset pinned above by id and version, rebuild the strategy
and the evaluator the manifest records, and re-execute with
`run_from_manifest`: the order and equity artefact hashes must match
byte for byte, or the mismatch is a defect to investigate
(methodology §3). Engine contract: docs/architecture/backtesting.md;
reporting rules: docs/research/backtesting-methodology.md sections 4-6.
"""
