"""Manifest tests: §3's field set, content-hash run ids, re-execution.

The reproduction test is the load-bearing one: a manifest stored as
JSON text, reloaded, re-run against the pinned dataset must produce a
result equal to the original **and** a byte-identical manifest when
rebuilt. Everything else here defends that path: tampered payloads are
refused by their own run id before any data loads, unknown models are
refused rather than guessed, a strategy that is not the recorded one is
refused field-for-field, and a run whose artefact hashes move raises
the defect signal of methodology §3.

The store fixture is the golden scenario written as CSV — the same five
bars test_engine works out by hand — so a reproduced run's numbers are
the same hand-checked ones.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

import harsh_quant_os.backtesting.manifest as manifest_module
from harsh_quant_os.backtesting import (
    MANIFEST_VERSION,
    BacktestConfig,
    BacktestError,
    BacktestResult,
    BpsCommission,
    CommissionModel,
    DecisionContext,
    FixedBpsSlippage,
    ReproductionMismatch,
    SlippageModel,
    build_manifest,
    compute_run_id,
    load_backtest_data,
    manifest_from_json,
    manifest_to_json,
    run_backtest,
    run_from_manifest,
)
from harsh_quant_os.config import Settings
from harsh_quant_os.quant.recipes.recipe import RecipeError
from harsh_quant_os.safety import ConfiguredRiskEvaluator
from harsh_quant_os.version import __version__
from tests.backtesting.test_engine import Threshold, _config
from tests.quant.test_recipes import _csv_bytes, _write_store

pytestmark = pytest.mark.backtesting

#: The golden bars as stored rows (open/high/low/close/volume as
#: test_engine's helper derives them: high = max + 1, low = min - 1).
GOLDEN_ROWS = (
    "XBTUSD,1m,2024-01-01T00:00:00+00:00,100,101,99,100,10",
    "XBTUSD,1m,2024-01-01T00:01:00+00:00,102,105,101,104,10",
    "XBTUSD,1m,2024-01-01T00:02:00+00:00,105,106,102,103,10",
    "XBTUSD,1m,2024-01-01T00:03:00+00:00,101,102,99,100,10",
    "XBTUSD,1m,2024-01-01T00:04:00+00:00,99,100,97,98,10",
)


def _store(tmp_path: Path) -> Path:
    """Write the golden dataset into a content-addressed store."""
    _write_store(tmp_path, "test.bars", _csv_bytes(GOLDEN_ROWS))
    return tmp_path


def _fresh_risk() -> ConfiguredRiskEvaluator:
    """A new evaluator, as every run and reproduction must use."""
    return ConfiguredRiskEvaluator(Settings.load(_env_file=None))


def _stored_run(tmp_path: Path) -> BacktestResult:
    data = load_backtest_data(_store(tmp_path), "test.bars")
    return run_backtest(data, Threshold(), _config(), risk=_fresh_risk())


def _manifest_for(tmp_path: Path) -> dict[str, object]:
    data = load_backtest_data(_store(tmp_path), "test.bars")
    risk = _fresh_risk()
    result = run_backtest(data, Threshold(), _config(), risk=risk)
    return build_manifest(result, config=_config(), risk=risk)


def _tamper(manifest: dict[str, object], **changes: object) -> dict[str, object]:
    """A tampered manifest whose run id is recomputed to match it.

    Tampering that keeps the id *valid* is the interesting adversary:
    it clears the integrity check and must still be refused by the
    content checks behind it.
    """
    altered = dict(manifest)
    altered.update(changes)
    altered["run_id"] = compute_run_id(altered)
    return altered


# ---------------------------------------------------------------------------
# Field set (§3)
# ---------------------------------------------------------------------------


def test_manifest_records_every_section_3_field(tmp_path: Path) -> None:
    result = _stored_run(tmp_path)
    manifest = build_manifest(result, config=_config(), risk=_fresh_risk())

    for key in (
        "manifest_version",
        "run_id",
        "git_sha",
        "engine_version",
        "timezone",
        "seed",
        "dataset",
        "universe",
        "strategy",
        "capital",
        "commission",
        "slippage",
        "intrabar_rule",
        "risk_limits",
        "results",
    ):
        assert key in manifest, f"section 3 requires {key}"

    assert manifest["manifest_version"] == MANIFEST_VERSION
    assert manifest["engine_version"] == __version__
    assert manifest["timezone"] == "UTC"
    # The engine has no RNG; the field is recorded as the null it is.
    assert manifest["seed"] is None
    assert manifest["intrabar_rule"] == "next_bar_open"

    git_sha = manifest["git_sha"]
    assert git_sha is None or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", str(git_sha))

    dataset = cast(dict[str, object], manifest["dataset"])
    assert dataset["id"] == "test.bars"
    # Recomputed independently: the version is the artefact's own hash.
    assert dataset["version"] == hashlib.sha256(_csv_bytes(GOLDEN_ROWS)).hexdigest()
    assert dataset["symbol"] == "XBTUSD"
    assert dataset["timeframe"] == "1m"
    assert dataset["bars"] == 5
    assert dataset["start"] == "2024-01-01T00:00:00+00:00"
    assert dataset["end"] == "2024-01-01T00:04:00+00:00"

    universe = cast(dict[str, object], manifest["universe"])
    assert universe["instruments"] == ["XBTUSD"]
    assert universe["as_of"] == "2024-01-01T00:04:00+00:00"

    strategy = cast(dict[str, object], manifest["strategy"])
    assert strategy["name"] == "threshold"
    assert strategy["parameters"] == {"entry": "close > 100", "target_qty": "2"}

    assert manifest["capital"] == "1000"
    assert manifest["commission"] == {
        "type": "bps_commission",
        "rate_bps": "5",
        "fixed_fee": "0",
    }
    assert manifest["slippage"] == {"type": "fixed_bps_slippage", "bps": "10"}

    limits = cast(dict[str, object], manifest["risk_limits"])
    assert limits["max_position_notional"] == "100000.0"
    assert limits["max_daily_loss"] == "5000.0"
    assert limits["max_open_positions"] == "5"

    results = cast(dict[str, object], manifest["results"])
    for key in ("result_sha256", "orders_sha256", "equity_sha256"):
        assert re.fullmatch(r"[0-9a-f]{64}", str(results[key])), key
    assert results["filled"] == 2
    assert results["expired"] == 0
    assert results["rejected"] == 0
    assert results["starting_capital"] == "1000"
    assert results["ending_equity"] == "987.387994"
    assert results["realised_pnl"] == "-12.408"
    assert results["total_commission"] == "0.204006"

    # The id is exactly what this build derives from the payload.
    assert manifest["run_id"] == compute_run_id(manifest)


def test_manifest_is_byte_identical_across_builds(tmp_path: Path) -> None:
    first = _manifest_for(tmp_path)
    second = _manifest_for(tmp_path)
    assert first == second
    assert manifest_to_json(first) == manifest_to_json(second)


def test_run_id_tracks_the_recorded_inputs(tmp_path: Path) -> None:
    baseline = _manifest_for(tmp_path)

    # A genuinely different run: double the capital.
    data = load_backtest_data(_store(tmp_path), "test.bars")
    richer = run_backtest(
        data,
        Threshold(),
        BacktestConfig(
            starting_capital=Decimal(2000),
            commission=BpsCommission(rate_bps=Decimal(5)),
            slippage=FixedBpsSlippage(bps=Decimal(10)),
        ),
        risk=_fresh_risk(),
    )
    other_capital = build_manifest(richer, config=_config(), risk=_fresh_risk())
    assert other_capital["run_id"] != baseline["run_id"]

    # A different strategy parameterisation: same rule, size 3.
    class ThresholdThree:
        name = "threshold"

        def decide(self, context: DecisionContext) -> Decimal | None:
            return Decimal(3) if context.bar.close > 100 else Decimal(0)

        def describe(self) -> dict[str, str]:
            return {"entry": "close > 100", "target_qty": "3"}

    other_parameters = run_backtest(data, ThresholdThree(), _config(), risk=_fresh_risk())
    different_strategy = build_manifest(other_parameters, config=_config(), risk=_fresh_risk())
    assert different_strategy["run_id"] != baseline["run_id"]

    # And a payload edited in place: its derived id differs from the
    # recorded one (the integrity check run_from_manifest applies).
    tampered = _tamper(dict(baseline), capital="2000")
    assert tampered["run_id"] != baseline["run_id"]
    assert compute_run_id(tampered) == tampered["run_id"]


def test_json_round_trip(tmp_path: Path) -> None:
    manifest = _manifest_for(tmp_path)
    text = manifest_to_json(manifest)
    parsed = manifest_from_json(text)
    assert parsed == manifest
    assert manifest_to_json(parsed) == text

    with pytest.raises(BacktestError, match="not valid JSON"):
        manifest_from_json("this is not json")
    with pytest.raises(BacktestError, match="JSON object"):
        manifest_from_json("[1, 2, 3]")


# ---------------------------------------------------------------------------
# Reproduction
# ---------------------------------------------------------------------------


def test_reproduces_byte_identically_from_stored_json(tmp_path: Path) -> None:
    original = _manifest_for(tmp_path)
    text = manifest_to_json(original)
    stored = manifest_from_json(text)

    reproduced = run_from_manifest(
        tmp_path,
        stored,
        strategy=Threshold(),
        risk=_fresh_risk(),
    )

    # Equal to the original run in every field, then the manifest
    # rebuilt from the reproduction is the same bytes.
    data = load_backtest_data(_store(tmp_path), "test.bars")
    assert reproduced == run_backtest(data, Threshold(), _config(), risk=_fresh_risk())
    rebuilt = build_manifest(reproduced, config=_config(), risk=_fresh_risk())
    assert manifest_to_json(rebuilt) == text


def test_an_altered_manifest_is_refused_before_anything_runs(
    tmp_path: Path,
) -> None:
    manifest = _manifest_for(tmp_path)
    altered = dict(manifest)
    altered["capital"] = "999999"  # id left as recorded: mismatch detected
    with pytest.raises(BacktestError, match="does not match its own payload"):
        run_from_manifest(tmp_path, altered, strategy=Threshold(), risk=_fresh_risk())


def test_a_wrong_strategy_is_refused_field_for_field(tmp_path: Path) -> None:
    manifest = _manifest_for(tmp_path)

    class OtherName:
        name = "not-threshold"

        def decide(self, context: object) -> Decimal | None:
            return None

        def describe(self) -> dict[str, str]:
            return {"entry": "close > 100", "target_qty": "2"}

    class OtherParams:
        name = "threshold"

        def decide(self, context: object) -> Decimal | None:
            return None

        def describe(self) -> dict[str, str]:
            return {"entry": "close > 100", "target_qty": "3"}

    with pytest.raises(BacktestError, match="does not match the manifest"):
        run_from_manifest(tmp_path, manifest, strategy=OtherName(), risk=_fresh_risk())
    with pytest.raises(BacktestError, match="does not match the manifest"):
        run_from_manifest(tmp_path, manifest, strategy=OtherParams(), risk=_fresh_risk())


def test_unknown_cost_models_are_refused_not_guessed(tmp_path: Path) -> None:
    manifest = _manifest_for(tmp_path)

    unknown_commission = _tamper(manifest, commission={"type": "mystery_fee_curve"})
    with pytest.raises(BacktestError, match="unknown commission model"):
        run_from_manifest(tmp_path, unknown_commission, strategy=Threshold(), risk=_fresh_risk())

    unknown_slippage = _tamper(manifest, slippage={"type": "order_book_sim"})
    with pytest.raises(BacktestError, match="unknown slippage model"):
        run_from_manifest(tmp_path, unknown_slippage, strategy=Threshold(), risk=_fresh_risk())


def test_missing_and_ill_typed_keys_are_named(tmp_path: Path) -> None:
    with pytest.raises(BacktestError, match="missing required key 'run_id'"):
        run_from_manifest(tmp_path, {}, strategy=Threshold(), risk=_fresh_risk())

    manifest = _manifest_for(tmp_path)
    not_a_string = dict(manifest)
    not_a_string["run_id"] = 42
    with pytest.raises(BacktestError, match="'run_id' must be a string"):
        run_from_manifest(tmp_path, not_a_string, strategy=Threshold(), risk=_fresh_risk())

    future_layout = _tamper(manifest, manifest_version=99)
    with pytest.raises(BacktestError, match="manifest_version 99"):
        run_from_manifest(tmp_path, future_layout, strategy=Threshold(), risk=_fresh_risk())


def test_a_pin_to_a_version_that_is_not_stored_is_refused(
    tmp_path: Path,
) -> None:
    manifest = _manifest_for(tmp_path)
    bad_pin = _tamper(
        manifest,
        dataset={**cast(dict[str, object], manifest["dataset"]), "version": "b" * 64},
    )
    with pytest.raises(RecipeError, match="has no version"):
        run_from_manifest(tmp_path, bad_pin, strategy=Threshold(), risk=_fresh_risk())


def test_unsupported_intrabar_rules_are_refused(tmp_path: Path) -> None:
    manifest = _manifest_for(tmp_path)
    foreign_rule = _tamper(manifest, intrabar_rule="close_fill")
    with pytest.raises(BacktestError, match="does not implement"):
        run_from_manifest(tmp_path, foreign_rule, strategy=Threshold(), risk=_fresh_risk())


def test_a_hash_that_moves_is_the_defect_signal(tmp_path: Path) -> None:
    manifest = _manifest_for(tmp_path)
    results = dict(cast(dict[str, object], manifest["results"]))
    results["orders_sha256"] = "0" * 64
    falsified = _tamper(manifest, results=results)

    with pytest.raises(ReproductionMismatch, match="did not reproduce orders"):
        run_from_manifest(tmp_path, falsified, strategy=Threshold(), risk=_fresh_risk())


def _real_git_head() -> str | None:
    """``git rev-parse HEAD`` asked independently of the code under test."""
    repo_root = Path(manifest_module.__file__).resolve().parents[3]
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    candidate = completed.stdout.strip()
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", candidate):
        return candidate
    return None


def test_git_sha_is_read_or_null_never_invented(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest_for(tmp_path)
    git_sha = manifest["git_sha"]

    # Asked independently: when this checkout answers, the manifest
    # must carry git's own bytes — a silently-null field would be a
    # provenance hole, not an honest fallback.
    expected = _real_git_head()
    if expected is None:
        assert git_sha is None  # git unavailable: null, never invented
    else:
        assert git_sha == expected
    assert manifest["run_id"] == compute_run_id(manifest)

    # git's default SHA-1 object format is 40 hex characters; a check
    # that accepted only 64-character digests rejected every real
    # rev-parse answer and recorded null forever. Both real forms must
    # pass through verbatim.
    for real_form in (
        "0123456789abcdef0123456789abcdef01234567",  # SHA-1 repository
        "0123456789abcdef" * 4,  # SHA-256 repository
    ):
        answer = subprocess.CompletedProcess(
            args=["git", "rev-parse", "HEAD"],
            returncode=0,
            stdout=real_form + "\n",
            stderr="",
        )
        # Patching the shared module's attribute is exactly what the
        # code under test resolves at call time.
        monkeypatch.setattr(subprocess, "run", lambda *args, _answer=answer, **kwargs: _answer)
        assert manifest_module._git_sha() == real_form

    # With git unavailable, the field becomes null and the id still works.
    monkeypatch.setattr(manifest_module, "_git_sha", lambda: None)
    without_git = _manifest_for(tmp_path)
    assert without_git["git_sha"] is None
    assert without_git["run_id"] == compute_run_id(without_git)
    if git_sha is not None:
        assert without_git["run_id"] != manifest["run_id"]


def test_models_that_cannot_be_recorded_are_refused(tmp_path: Path) -> None:
    result = _stored_run(tmp_path)

    class OpaqueCommission:
        def apply(self, notional: Decimal) -> Decimal:
            return Decimal(0)

    class OpaqueSlippage:
        def apply(self, reference: Decimal, *, buy: bool) -> Decimal:
            return reference

    with pytest.raises(BacktestError, match="cannot serialise commission model"):
        build_manifest(
            result,
            config=BacktestConfig(
                starting_capital=Decimal(1000),
                commission=cast(CommissionModel, OpaqueCommission()),
                slippage=FixedBpsSlippage(bps=Decimal(0)),
            ),
            risk=_fresh_risk(),
        )
    with pytest.raises(BacktestError, match="cannot serialise slippage model"):
        build_manifest(
            result,
            config=BacktestConfig(
                starting_capital=Decimal(1000),
                commission=BpsCommission(rate_bps=Decimal(0)),
                slippage=cast(SlippageModel, OpaqueSlippage()),
            ),
            risk=_fresh_risk(),
        )
