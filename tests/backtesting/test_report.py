"""Report tests: the methodology's reporting rules, asserted on text.

backtesting-methodology.md §6 and backtesting.md §5 are checkable
claims: limitations first, manifest attached, assumptions separated
from measurements, the standard caveat present, conditional language,
small samples called out, undefined figures rendered as undefined —
and, machine-checked, none of the FORBIDDEN_CLAIMS phrases. Each test
below is one rule, so a rule that stops holding fails by name.

The cost-sensitivity expectations are hand-computed from the golden
scenario at 0.5x and 2x costs (fill prices move with slippage, so the
runs are genuinely different traces, not scaled endings).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import cast

import pytest

from harsh_quant_os.backtesting import (
    BacktestConfig,
    BacktestError,
    BacktestResult,
    BpsCommission,
    CommissionModel,
    CostSensitivityPoint,
    DecisionContext,
    FixedBpsSlippage,
    RunMetrics,
    SlippageModel,
    Strategy,
    WindowCoverage,
    build_manifest,
    build_report,
    compute_metrics,
    cost_sensitivity,
    run_backtest,
    wilson_interval,
    window_coverage,
)
from harsh_quant_os.backtesting.report import (
    SMALL_SAMPLE_TRADE_THRESHOLD,
)
from harsh_quant_os.config import Settings
from harsh_quant_os.data.providers import Bar
from harsh_quant_os.safety import ConfiguredRiskEvaluator
from harsh_quant_os.safety.risk import RiskEvaluator
from tests.backtesting.test_engine import (
    GOLDEN_BARS,
    ApproveAll,
    Threshold,
    _bar,
    _config,
    _data,
)

pytestmark = pytest.mark.backtesting

_REQUIRED_SECTIONS = (
    "## Limitations (read first)",
    "## Caveat",
    "## Run manifest",
    "## Assumptions (these are not measurements)",
    "## Measured results (this sample only)",
    "## Uncertainty",
    "## Cost sensitivity",
    "## Coverage and universe",
    "## Reproducing this run",
)

_NOTE = "Reference parameters chosen to make this run possible, not searched."


class Never:
    """A strategy that never trades — the zero-trade baseline."""

    name = "never"

    def decide(self, context: DecisionContext) -> Decimal | None:
        return None

    def describe(self) -> dict[str, str]:
        return {}


def _fresh_risk() -> ConfiguredRiskEvaluator:
    return ConfiguredRiskEvaluator(Settings.load(_env_file=None))


def _parts(
    bars: Sequence[Bar] = GOLDEN_BARS,
    strategy: Strategy | None = None,
) -> tuple[BacktestResult, dict[str, object], RunMetrics, WindowCoverage]:
    """The golden run's four report inputs, built the way the CLI does."""
    data = _data(tuple(bars))
    risk = _fresh_risk()
    result = run_backtest(data, strategy or Threshold(), _config(), risk=risk)
    manifest = build_manifest(result, config=_config(), risk=risk)
    return result, manifest, compute_metrics(result), window_coverage(data)


def _report(
    *,
    bars: Sequence[Bar] = GOLDEN_BARS,
    strategy: Strategy | None = None,
    sensitivity: Sequence[CostSensitivityPoint] | None = None,
    note: str | None = _NOTE,
) -> str:
    result, manifest, metrics, coverage = _parts(bars, strategy)
    return build_report(
        result,
        manifest=manifest,
        metrics=metrics,
        coverage=coverage,
        sensitivity=sensitivity,
        strategy_note=note,
    )


def _section(text: str, heading: str, next_heading: str) -> str:
    """The slice of the report between two headings."""
    return text.split(heading, 1)[1].split(next_heading, 1)[0]


# ---------------------------------------------------------------------------
# Structure: §6 ordering and required content
# ---------------------------------------------------------------------------


def test_limitations_are_the_first_heading_not_the_last() -> None:
    report = _report()
    headings = [line for line in report.splitlines() if line.startswith("## ")]
    assert headings[0] == "## Limitations (read first)"


def test_every_required_section_is_present() -> None:
    report = _report()
    for section in _REQUIRED_SECTIONS:
        assert section in report, f"missing required section: {section}"


def test_the_standard_caveat_and_conditional_language_are_present() -> None:
    report = _report().lower()
    assert "past performance is not indicative of future results." in report
    assert "under these assumptions" in report
    assert "in this sample" in report
    # The claim a backtest does not make, stated as not made:
    assert 'never "what will happen"' in report


def test_in_sample_status_and_small_samples_are_called_out() -> None:
    report = _report()
    assert "entirely in-sample" in report
    assert "no train/test split or out-of-sample segment" in report
    # One completed trip, against the stated threshold.
    assert "1 completed round trips" in report
    assert f"below the {SMALL_SAMPLE_TRADE_THRESHOLD}-trade threshold" in report
    # The four-minute sample gets the annualisation warning.
    assert "Annualised figures extrapolate" in report


def test_the_variants_tried_line_is_honest_about_being_unknown() -> None:
    report = _report()
    assert "Variants tried: not recorded for this run." in report
    assert "multiple-testing context is unavailable" in report


def test_the_report_is_deterministic() -> None:
    assert _report() == _report()


# ---------------------------------------------------------------------------
# The machine-checked language rule
# ---------------------------------------------------------------------------


def test_generated_report_contains_no_forbidden_claims() -> None:
    from tests.unit.test_documentation import FORBIDDEN_CLAIMS

    report = _report().lower()
    offenders = [claim for claim in FORBIDDEN_CLAIMS if claim in report]
    assert offenders == []


# ---------------------------------------------------------------------------
# Manifest attached, assumptions separated from measurements
# ---------------------------------------------------------------------------


def test_the_manifest_is_attached_with_every_section_3_key() -> None:
    result, manifest, metrics, coverage = _parts()
    report = build_report(result, manifest=manifest, metrics=metrics, coverage=coverage)

    assert str(manifest["run_id"]) in report
    for key in manifest:
        assert f'"{key}"' in report, f"manifest key {key} not attached"


def test_assumptions_and_measurements_live_in_separate_sections() -> None:
    report = _report()
    assumptions = _section(report, "## Assumptions", "## Measured results")
    measured = _section(report, "## Measured results", "## Uncertainty")

    # Cost/risk conventions are assumptions...
    assert "type=bps_commission" in assumptions
    assert "type=fixed_bps_slippage" in assumptions
    assert "metric conventions" in assumptions.lower()
    # ...and measured figures are not.
    assert "| total return |" in measured
    assert "| maximum drawdown |" in measured
    assert "type=bps_commission" not in measured
    # Drawdown sits beside return, as §5 requires.
    assert "peak " in measured and "under water" in measured


def test_the_strategy_note_is_disclosed_as_a_limitation() -> None:
    report = _report()
    limitations = _section(report, "## Limitations", "## Caveat")
    assert _NOTE in limitations


# ---------------------------------------------------------------------------
# Undefined figures stay undefined
# ---------------------------------------------------------------------------


def test_a_zero_trade_run_renders_none_not_a_number() -> None:
    report = _report(strategy=Never())

    assert "0 completed round trips" in report
    assert "not defined" in report  # volatility and Sharpe
    assert "zero dispersion" in report  # their reason, attached
    assert "No completed round trips, so no interval" in report
    assert "no winning round trips" in report
    # Hit rate is absent as a number because nothing was traded.
    assert "| hit rate |" not in report


def test_a_covered_window_and_a_gapped_window_report_themselves() -> None:
    complete = _report()
    assert "coverage complete" in complete
    assert "counted here, never interpolated" in complete or (
        "contiguous across their span" in complete
    )

    gapped = _report(
        bars=(
            _bar(0, "100", "101"),
            _bar(2, "100", "101"),
            _bar(3, "100", "101"),
            _bar(5, "100", "101"),
        )
    )
    assert "2 bars are missing across 2 gap interval(s)" in gapped
    assert "counted here, never interpolated" in gapped
    assert "coverage incomplete" in gapped


def test_an_uncomputable_window_says_so_instead_of_estimating() -> None:
    monthly = _report(
        bars=(
            _bar(0, "100", "101", timeframe="1mo"),
            _bar(59, "100", "101", timeframe="1mo"),
        )
    )
    assert "gap analysis not computable" in monthly
    assert "stated here rather than estimated" in monthly


# ---------------------------------------------------------------------------
# Cost sensitivity (methodology §5: cost optimism)
# ---------------------------------------------------------------------------


def test_cost_sensitivity_runs_each_factor_with_a_fresh_evaluator() -> None:
    builds: list[int] = []

    def factory() -> RiskEvaluator:
        builds.append(1)
        return ApproveAll()

    points = cost_sensitivity(_data(), Threshold(), _config(), risk_factory=factory)

    assert [point.factor for point in points] == [
        Decimal("0.5"),
        Decimal(1),
        Decimal(2),
    ]
    assert len(builds) == 3  # one evaluator per run, never reused

    # Factor 1 reproduces the base run exactly (same numbers, same fills).
    assert points[1].ending_equity == Decimal("987.387994")
    assert points[1].total_commission == Decimal("0.204006")
    assert points[1].filled == 2

    # 0.5x costs, hand-traced: buy fill 105 * 1.0005 = 105.0525,
    # fee 210.105 * 0.00025 = 0.05252625, cash 789.84247375;
    # sell fill 99 * 0.9995 = 98.9505, fee 197.901 * 0.00025 =
    # 0.04947525, cash 789.84247375 + 197.901 - 0.04947525
    # = 987.6939985; commissions 0.05252625 + 0.04947525 = 0.1020015.
    assert points[0].ending_equity == Decimal("987.6939985")
    assert points[0].total_commission == Decimal("0.1020015")
    assert points[0].filled == 2

    # 2x costs: buy fill 105 * 1.002 = 105.21, fee 0.21042, cash
    # 789.36958; sell fill 99 * 0.998 = 98.802, fee 0.197604, cash
    # 789.36958 + 197.604 - 0.197604 = 986.775976; commissions
    # 0.21042 + 0.197604 = 0.408024.
    assert points[2].ending_equity == Decimal("986.775976")
    assert points[2].total_commission == Decimal("0.408024")
    assert points[2].filled == 2

    # Cheaper costs end higher than the base ends higher than
    # costlier costs — the direction cost optimism would hide.
    assert points[0].ending_equity > points[1].ending_equity > points[2].ending_equity


def test_cost_sensitivity_refuses_models_it_cannot_scale() -> None:
    class Opaque:
        def apply(self, notional: Decimal) -> Decimal:
            return Decimal(0)

    class OpaqueSlippage:
        def apply(self, reference: Decimal, *, buy: bool) -> Decimal:
            return reference

    with pytest.raises(BacktestError, match="can only scale a bps_commission"):
        cost_sensitivity(
            _data(),
            Threshold(),
            BacktestConfig(
                starting_capital=Decimal(1000),
                commission=cast(CommissionModel, Opaque()),
                slippage=FixedBpsSlippage(bps=Decimal(0)),
            ),
            risk_factory=lambda: ApproveAll(),
        )
    with pytest.raises(BacktestError, match="can only scale a fixed_bps_slippage"):
        cost_sensitivity(
            _data(),
            Threshold(),
            BacktestConfig(
                starting_capital=Decimal(1000),
                commission=BpsCommission(rate_bps=Decimal(0)),
                slippage=cast(SlippageModel, OpaqueSlippage()),
            ),
            risk_factory=lambda: ApproveAll(),
        )


def test_the_report_shows_the_table_or_admits_it_was_not_run() -> None:
    result, manifest, metrics, coverage = _parts()

    absent = build_report(result, manifest=manifest, metrics=metrics, coverage=coverage)
    assert "Cost sensitivity was not computed for this report" in absent

    points = cost_sensitivity(_data(), Threshold(), _config(), risk_factory=lambda: ApproveAll())
    present = build_report(
        result,
        manifest=manifest,
        metrics=metrics,
        coverage=coverage,
        sensitivity=points,
    )
    assert "| 0.5x | 987.69399850 | 0.10200150 | 2 |" in present
    assert "| 2x | 986.775976 | 0.408024 | 2 |" in present


# ---------------------------------------------------------------------------
# Uncertainty: the one interval, hand-verifiable
# ---------------------------------------------------------------------------


def test_the_wilson_interval_restates_the_formula_by_hand() -> None:
    z = Decimal("1.959963984540054")
    count = Decimal(1)
    proportion = Decimal(0)
    z_squared = z * z
    denominator = Decimal(1) + z_squared / count
    centre = (proportion + z_squared / (2 * count)) / denominator
    margin = (
        z * ((proportion * (1 - proportion) + z_squared / (4 * count)) / count).sqrt() / denominator
    )

    zero_of_one = wilson_interval(0, 1)
    one_of_one = wilson_interval(1, 1)
    assert zero_of_one is not None
    assert one_of_one is not None
    assert zero_of_one == (centre - margin, centre + margin)

    lower, upper = one_of_one
    assert lower > 0
    assert upper <= Decimal(1)
    # (s, n) mirrors (n - s, n): identical width, reflected interval.
    assert (upper - lower) == (zero_of_one[1] - zero_of_one[0])


def test_the_wilson_interval_refuses_nonsense_and_absence() -> None:
    assert wilson_interval(0, 0) is None  # no trials is not a zero-width result
    assert wilson_interval(0, -1) is None
    with pytest.raises(BacktestError, match="0 <= successes <= trials"):
        wilson_interval(5, 3)


def test_the_uncertainty_section_states_its_assumptions() -> None:
    report = _report()
    uncertainty = _section(report, "## Uncertainty", "## Cost sensitivity")
    assert "Wilson 95% interval" in uncertainty
    assert "assumes independent, identically distributed trials" in uncertainty
    assert f"against the {SMALL_SAMPLE_TRADE_THRESHOLD}-trade threshold" in uncertainty
