"""The run manifest: what a backtest was, and how to prove it again.

backtesting-methodology.md §3: every run records
``run_id · git sha · engine version · dataset versions · universe
(as-of) · parameters · cost model + inputs · slippage model + inputs ·
seed · start/end · timezone · result artefact hashes``, and
"re-executing a manifest must reproduce the numbers. Failure to
reproduce is treated as a defect in the engine or the data —
investigated, not explained away."

Design commitments:

- **Fully deterministic.** The manifest carries no wall clock, no
  randomness, no environment snapshot that a second identical run
  could not produce: the simulation period (§3's start/end) is the
  dataset's own first/last timestamps, and ``seed`` is recorded
  ``null`` because this engine consumes no randomness at all. Two
  builds over the same result produce byte-identical JSON.
- **``run_id`` is a content hash**, not a counter: SHA-256 over the
  canonical JSON of the manifest minus its own ``run_id`` field. A
  tampered digit anywhere in the payload invalidates it, and
  :func:`run_from_manifest` refuses such a manifest before running
  anything.
- **Reconstruction is closed-world.** Data, capital and the two cost
  models are rebuilt from a whitelist of shapes this build knows
  (``bps_commission``, ``fixed_bps_slippage``); anything else raises
  rather than being guessed — no dynamic import, no ``eval``
  (the same rule the feature-recipe executor follows). The strategy
  itself is *supplied by the caller* and checked field-for-field
  against the record: code cannot safely be reconstructed from data,
  but the manifest can prove the code you brought is the code that
  ran.
- **Git SHA** is read by running ``git rev-parse HEAD`` at the
  repository root; when git is unavailable (installed package, unborn
  HEAD) the field is ``null`` — never invented.

Re-execution compares SHA-256 hashes of three artefacts — the order
log, the equity curve, and the whole result — and raises
:class:`~harsh_quant_os.backtesting.errors.ReproductionMismatch`
naming the artefact that moved.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from harsh_quant_os.backtesting.costs import (
    BpsCommission,
    CommissionModel,
    FixedBpsSlippage,
    SlippageModel,
)
from harsh_quant_os.backtesting.data import load_backtest_data
from harsh_quant_os.backtesting.engine import (
    NEXT_BAR_OPEN,
    BacktestConfig,
    BacktestResult,
    run_backtest,
)
from harsh_quant_os.backtesting.errors import BacktestError, ReproductionMismatch
from harsh_quant_os.backtesting.strategy import Strategy
from harsh_quant_os.safety.risk import RiskEvaluator
from harsh_quant_os.version import __version__

__all__ = [
    "MANIFEST_VERSION",
    "build_manifest",
    "compute_run_id",
    "manifest_from_json",
    "manifest_to_json",
    "run_from_manifest",
]

#: Bumped when the manifest's own layout changes incompatibly.
MANIFEST_VERSION = 1

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# git's own revision forms: SHA-1 (40 hex, git's default object
# format) or SHA-256 repositories (64 hex).
_GIT_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


# ---------------------------------------------------------------------------
# Artefact hashing
# ---------------------------------------------------------------------------


def _canonical(payload: object) -> str:
    """Canonical JSON: sorted keys, compact, ASCII — byte-stable."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _orders_payload(result: BacktestResult) -> list[dict[str, Any]]:
    """The order log as JSON-ready records (exact decimals as strings)."""
    return [
        {
            "commission": str(order.commission),
            "decision_time": order.decision_time.isoformat(),
            "delta": str(order.delta),
            "fill_price": str(order.fill_price) if order.fill_price is not None else None,
            "fill_time": order.fill_time.isoformat() if order.fill_time is not None else None,
            "note": order.note,
            "reference_open": (
                str(order.reference_open) if order.reference_open is not None else None
            ),
            "status": order.status.value,
            "target": str(order.target),
        }
        for order in result.orders
    ]


def _equity_payload(result: BacktestResult) -> list[dict[str, Any]]:
    """The equity curve as JSON-ready records."""
    return [
        {
            "close": str(point.close),
            "equity": str(point.equity),
            "position": str(point.position),
            "time": point.time.isoformat(),
        }
        for point in result.equity_curve
    ]


def _result_payload(result: BacktestResult) -> dict[str, Any]:
    """Everything one run produced, in one canonical structure."""
    return {
        "ending_cash": str(result.ending_cash),
        "ending_equity": str(result.ending_equity),
        "ending_quantity": str(result.ending_quantity),
        "ending_unrealised": str(result.ending_unrealised),
        "equity_curve": _equity_payload(result),
        "orders": _orders_payload(result),
        "realised_pnl": str(result.realised_pnl),
        "starting_capital": str(result.starting_capital),
        "total_commission": str(result.total_commission),
    }


def _sha256_of(payload: object) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Provenance helpers
# ---------------------------------------------------------------------------


def _git_sha() -> str | None:
    """HEAD of the repository containing this file, or ``None``.

    Never invented: git's own answer, or nothing. Subprocess with an
    argument list (no shell), short timeout, all failures → ``None``.

    The accepted form is git's own: 40 hex characters for a SHA-1
    object format (git's default), 64 for a SHA-256 repository.
    Validating against 64 alone would reject every real ``rev-parse``
    answer and silently record null forever.
    """
    repo_root = Path(__file__).resolve().parents[3]
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
    return candidate if _GIT_SHA_RE.fullmatch(candidate) else None


def _commission_record(model: CommissionModel) -> dict[str, str]:
    """A commission model as manifest JSON — closed set, no guessing."""
    if isinstance(model, BpsCommission):
        return {
            "type": "bps_commission",
            "rate_bps": str(model.rate_bps),
            "fixed_fee": str(model.fixed_fee),
        }
    raise BacktestError(
        f"cannot serialise commission model {type(model).__name__} into a manifest: "
        "a run the manifest could not reproduce must not be recorded as "
        "reproducible (only bps_commission is known to this build)"
    )


def _slippage_record(model: SlippageModel) -> dict[str, str]:
    """A slippage model as manifest JSON — closed set, no guessing."""
    if isinstance(model, FixedBpsSlippage):
        return {"type": "fixed_bps_slippage", "bps": str(model.bps)}
    raise BacktestError(
        f"cannot serialise slippage model {type(model).__name__} into a manifest: "
        "a run the manifest could not reproduce must not be recorded as "
        "reproducible (only fixed_bps_slippage is known to this build)"
    )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_manifest(
    result: BacktestResult,
    *,
    config: BacktestConfig,
    risk: RiskEvaluator,
) -> dict[str, object]:
    """Build the deterministic §3 manifest for a finished run.

    Args:
        result: The run's recorded outcome (the artefacts get hashed).
        config: The capital and cost models the run used.
        risk: The evaluator consulted for every order. When it exposes
            ``limits()`` (the configured evaluator does) the limits are
            recorded; other evaluators record ``null`` rather than a
            guess.

    Returns:
        A JSON-ready dict containing every §3 field. ``run_id`` is the
        SHA-256 of the payload with ``run_id`` removed, so the record
        is self-verifying.

    Raises:
        BacktestError: A cost model this build cannot serialise (a
            run it could not reconstruct must not claim to be
            reproducible).
    """
    if not result.equity_curve:
        raise BacktestError("cannot build a manifest for a run with no equity curve")

    curve = result.equity_curve
    commission = _commission_record(config.commission)
    slippage = _slippage_record(config.slippage)

    limits_getter = getattr(risk, "limits", None)
    risk_limits: dict[str, str] | None = None
    if callable(limits_getter):
        candidate: object = limits_getter()
        if isinstance(candidate, dict) and all(
            isinstance(key, str) and isinstance(value, str) for key, value in candidate.items()
        ):
            risk_limits = dict(candidate)

    payload: dict[str, object] = {
        "manifest_version": MANIFEST_VERSION,
        "git_sha": _git_sha(),
        "engine_version": __version__,
        "timezone": "UTC",
        # The engine has no RNG: recorded as null, not as a number
        # that would pretend to seed something.
        "seed": None,
        "dataset": {
            "id": result.dataset_id,
            "version": result.dataset_version,
            "symbol": result.symbol,
            "timeframe": result.timeframe,
            "start": curve[0].time.isoformat(),
            "end": curve[-1].time.isoformat(),
            "bars": len(curve),
        },
        "universe": {
            "instruments": [result.symbol],
            "as_of": curve[-1].time.isoformat(),
        },
        "strategy": {
            "name": result.strategy_name,
            "parameters": dict(result.strategy_parameters),
        },
        "capital": str(result.starting_capital),
        "commission": commission,
        "slippage": slippage,
        "intrabar_rule": result.intrabar_rule,
        "risk_limits": risk_limits,
        "results": {
            "result_sha256": _sha256_of(_result_payload(result)),
            "orders_sha256": _sha256_of(_orders_payload(result)),
            "equity_sha256": _sha256_of(_equity_payload(result)),
            "starting_capital": str(result.starting_capital),
            "ending_cash": str(result.ending_cash),
            "ending_equity": str(result.ending_equity),
            "ending_quantity": str(result.ending_quantity),
            "realised_pnl": str(result.realised_pnl),
            "total_commission": str(result.total_commission),
            "filled": len(result.filled),
            "expired": len(result.expired),
            "rejected": len(result.rejected),
        },
    }
    payload["run_id"] = compute_run_id(payload)
    return payload


def compute_run_id(manifest: Mapping[str, object]) -> str:
    """SHA-256 over the manifest's canonical JSON, minus ``run_id``.

    Deterministic by construction: sorted keys, compact separators,
    exact decimals and timestamps already stored as strings. Changing
    any recorded fact changes the id; re-deriving it detects tampering.
    """
    payload = {key: value for key, value in manifest.items() if key != "run_id"}
    return _sha256_of(payload)


def manifest_to_json(manifest: Mapping[str, object]) -> str:
    """Canonical JSON text for storage (byte-identical across builds)."""
    return _canonical(dict(manifest))


def manifest_from_json(text: str) -> dict[str, object]:
    """Parse stored manifest JSON, refusing anything that is not an object.

    Raises:
        BacktestError: The text is not JSON, or the JSON top level is
            not an object.
    """
    try:
        parsed = json.loads(text)
    except ValueError as error:
        raise BacktestError(f"manifest is not valid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise BacktestError(f"manifest must be a JSON object, got {type(parsed).__name__}")
    return parsed


# ---------------------------------------------------------------------------
# Re-execution
# ---------------------------------------------------------------------------


def _require(mapping: Mapping[str, object], key: str) -> object:
    if key not in mapping:
        raise BacktestError(f"manifest is missing required key {key!r}")
    return mapping[key]


def _expect_mapping(value: object, key: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise BacktestError(f"manifest key {key!r} must be an object, got {type(value).__name__}")
    return value


def _expect_str(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise BacktestError(f"manifest key {key!r} must be a string, got {type(value).__name__}")
    return value


def _expect_int(value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BacktestError(f"manifest key {key!r} must be an integer, got {type(value).__name__}")
    return value


def _exact(value: object, key: str) -> Decimal:
    """Parse a manifest's exact-decimal string — refuse anything else."""
    text = _expect_str(value, key)
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError) as error:
        raise BacktestError(f"manifest key {key!r} is not an exact decimal: {text!r}") from error
    if not parsed.is_finite():
        raise BacktestError(f"manifest key {key!r} must be finite, got {text!r}")
    return parsed


def _commission_from(record: Mapping[str, object]) -> CommissionModel:
    kind = _expect_str(_require(record, "type"), "commission.type")
    if kind == "bps_commission":
        return BpsCommission(
            rate_bps=_exact(_require(record, "rate_bps"), "commission.rate_bps"),
            fixed_fee=_exact(_require(record, "fixed_fee"), "commission.fixed_fee"),
        )
    raise BacktestError(
        f"unknown commission model {kind!r} in manifest: refusing to guess a "
        "model this build does not know"
    )


def _slippage_from(record: Mapping[str, object]) -> SlippageModel:
    kind = _expect_str(_require(record, "type"), "slippage.type")
    if kind == "fixed_bps_slippage":
        return FixedBpsSlippage(
            bps=_exact(_require(record, "bps"), "slippage.bps"),
        )
    raise BacktestError(
        f"unknown slippage model {kind!r} in manifest: refusing to guess a "
        "model this build does not know"
    )


def _strategy_matches(manifest: Mapping[str, object], strategy: Strategy) -> None:
    """Verify the supplied strategy is the one the manifest recorded."""
    record = _expect_mapping(_require(manifest, "strategy"), "strategy")
    recorded_name = _expect_str(_require(record, "name"), "strategy.name")
    recorded_parameters = _expect_mapping(_require(record, "parameters"), "strategy.parameters")

    supplied_name = strategy.name
    if not isinstance(supplied_name, str) or not supplied_name.strip():
        raise BacktestError(f"strategy.name must be a non-empty string, got {supplied_name!r}")
    raw = strategy.describe()
    supplied_parameters: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise BacktestError(
                f"strategy.describe() must map strings to strings, got {key!r}: {value!r}"
            )
        supplied_parameters[key] = value

    if supplied_name != recorded_name or supplied_parameters != dict(recorded_parameters):
        raise BacktestError(
            "the supplied strategy does not match the manifest: manifest has "
            f"{recorded_name!r} {dict(recorded_parameters)!r}, supplied is "
            f"{supplied_name!r} {supplied_parameters!r} (reproduction requires "
            "the exact strategy that ran)"
        )


def run_from_manifest(
    root: Path,
    manifest: Mapping[str, object],
    *,
    strategy: Strategy,
    risk: RiskEvaluator,
) -> BacktestResult:
    """Re-execute a recorded run and verify it byte-for-byte.

    Steps, in order (each one fails closed):

    1. Re-derive ``run_id`` from the payload — a tampered manifest is
       refused before anything is loaded or run.
    2. Check the engine actually supports the recorded intrabar rule.
    3. Load the dataset pinned by id **and** version — the store
       recomputes the artefact hash, so changed data fails here.
    4. Rebuild capital and both cost models from the closed whitelist.
    5. Verify the supplied strategy matches the record field-for-field.
    6. Run, then compare the three artefact hashes; any difference
       raises :class:`ReproductionMismatch`.

    Args:
        root: The data root holding ``clean/``.
        manifest: The stored manifest (typically from
            :func:`manifest_from_json`).
        strategy: The strategy implementation to run — must match the
            recorded name and parameters.
        risk: A **fresh** evaluator (evaluators are per-run, like
            strategies).

    Returns:
        The reproduced result — equal to the original in every field
        when reproduction succeeds.

    Raises:
        BacktestError: Missing/ill-typed keys, run-id mismatch, unknown
            model, strategy mismatch, or an unsupported intrabar rule.
        RecipeError: The pinned dataset version is absent or its
            stored hash no longer matches.
        ReproductionMismatch: The run executed but produced different
            artefacts — the defect signal of §3.
    """
    run_id = compute_run_id(manifest)
    recorded_id = _expect_str(_require(manifest, "run_id"), "run_id")
    if recorded_id != run_id:
        raise BacktestError(
            "manifest run_id does not match its own payload: recorded "
            f"{recorded_id}, derived {run_id} — the manifest has been altered "
            "since it was written"
        )

    layout = _expect_int(_require(manifest, "manifest_version"), "manifest_version")
    if layout != MANIFEST_VERSION:
        raise BacktestError(
            f"manifest_version {layout} is not what this build understands "
            f"({MANIFEST_VERSION}); refusing to guess its layout"
        )

    rule = _expect_str(_require(manifest, "intrabar_rule"), "intrabar_rule")
    if rule != NEXT_BAR_OPEN:
        raise BacktestError(
            f"manifest records intrabar rule {rule!r}, which this engine does "
            f"not implement (only {NEXT_BAR_OPEN!r}); refusing to re-run it "
            "differently than it was run"
        )

    dataset_record = _expect_mapping(_require(manifest, "dataset"), "dataset")
    dataset = load_backtest_data(
        root,
        _expect_str(_require(dataset_record, "id"), "dataset.id"),
        version=_expect_str(_require(dataset_record, "version"), "dataset.version"),
    )

    config = BacktestConfig(
        starting_capital=_exact(_require(manifest, "capital"), "capital"),
        commission=_commission_from(
            _expect_mapping(_require(manifest, "commission"), "commission")
        ),
        slippage=_slippage_from(_expect_mapping(_require(manifest, "slippage"), "slippage")),
    )

    _strategy_matches(manifest, strategy)

    reproduced = run_backtest(dataset, strategy, config, risk=risk)

    recorded = _expect_mapping(_require(manifest, "results"), "results")
    comparisons = (
        ("orders_sha256", _orders_payload(reproduced)),
        ("equity_sha256", _equity_payload(reproduced)),
        ("result_sha256", _result_payload(reproduced)),
    )
    for key, payload in comparisons:
        expected = _expect_str(_require(recorded, key), f"results.{key}")
        actual = _sha256_of(payload)
        if actual != expected:
            raise ReproductionMismatch(
                f"re-execution did not reproduce {key.removesuffix('_sha256')}: "
                f"recorded {expected}, reproduced {actual} (methodology §3 — "
                "a defect to investigate, not to explain away)"
            )
    return reproduced
