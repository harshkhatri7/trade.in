"""Measure feature-recipe execution on a real stored dataset.

quant-engine.md §7 exit criterion 4: "Benchmark data documented;
performance measured, not assumed." This script does the measuring:

- loads a real dataset from ``data/clean`` through the same
  ``load_bar_batch`` path research code uses (the artefact's hash is
  re-verified against its content-addressed directory on the way in);
- builds a representative recipe (nine features, one chained through an
  earlier feature) pinned to that exact dataset version;
- executes it once cold, then ``--runs`` timed runs, and reports the
  measured wall times plus whether every run was **bit-identical** to
  the first — a benchmark of a non-deterministic pipeline would be
  meaningless, so reproduction is checked, not assumed.

What it prints is what was measured on this machine at run time; the
numbers recorded in the docs came from this script's output. It makes
no prediction about any future run, and it touches nothing live.

Usage (from the repository root)::

    .venv\\Scripts\\python.exe scripts\\quant\\benchmark_features.py [--runs 50] [--save]

Exit status: 0 when every run reproduced the first exactly, 1 when any
run differed (a determinism failure — report it, do not rerun until it
disappears).
"""

from __future__ import annotations

import argparse
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np

from harsh_quant_os.quant.recipes import (
    DatasetRef,
    FeatureRecipe,
    FeatureSpec,
    RecipeError,
    execute,
    load_bar_batch,
)
from harsh_quant_os.quant.registry import FeatureStore, canonical_matrix_sha256

DEFAULT_DATASET = "kraken.xbtusd.1m"
DEFAULT_DATA_ROOT = Path("data")
DEFAULT_STORE_ROOT = Path("data") / "features"


def build_recipe(version: str) -> FeatureRecipe:
    """The benchmark pipeline: eight features over close, one chained.

    Every op is a golden-tested primitive; ``sma_5_ema12`` reads an
    earlier feature, exercising the source chain the executor enforces.
    It chains from ``ema_12_close`` (first-value seeded, finite from row
    0) because primitives refuse to compute through another feature's
    warm-up NaN — that refusal is deliberate, not a benchmark shortcut.
    """
    return FeatureRecipe(
        recipe_version=1,
        inputs=(DatasetRef(dataset_id=DEFAULT_DATASET, version=version),),
        features=(
            FeatureSpec(name="sma_20_close", op="sma", source="close", params={"window": 20}),
            FeatureSpec(name="sma_50_close", op="sma", source="close", params={"window": 50}),
            FeatureSpec(name="ema_12_close", op="ema", source="close", params={"span": 12}),
            FeatureSpec(
                name="rolling_std_20_close",
                op="rolling_std",
                source="close",
                params={"window": 20},
            ),
            FeatureSpec(
                name="rolling_zscore_20_close",
                op="rolling_zscore",
                source="close",
                params={"window": 20},
            ),
            FeatureSpec(name="rsi_14_close", op="rsi", source="close", params={"period": 14}),
            FeatureSpec(name="log_ret_1", op="log_returns", source="close"),
            FeatureSpec(name="lag_1_close", op="lag", source="close", params={"periods": 1}),
            FeatureSpec(
                name="sma_5_ema12",
                op="sma",
                source="ema_12_close",
                params={"window": 5},
            ),
        ),
        nan_policy=("warm-up NaN retained; rows never dropped (quant-engine.md section 3 rule 3)"),
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Command-line options; all roots are explicit, none implied."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", default=DEFAULT_DATASET, help="stored dataset name")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=DEFAULT_DATA_ROOT,
        help="data root holding clean/ (default: data)",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE_ROOT,
        help="feature store root for --save (default: data/features)",
    )
    parser.add_argument("--runs", type=int, default=50, help="timed executions after one cold run")
    parser.add_argument(
        "--save",
        action="store_true",
        help="also file the executed recipe in the feature store and verify it",
    )
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    return args


def main(argv: list[str]) -> int:
    """Run the measurement and print what was measured. 0 = reproduced."""
    args = parse_args(argv)

    bars = load_bar_batch(args.data_root, args.name)
    recipe = build_recipe(bars.version)

    # Cold run: includes first-touch effects, reported separately rather
    # than hidden inside an average.
    started = time.perf_counter()
    reference = execute(recipe, bars)
    cold_ms = (time.perf_counter() - started) * 1000.0
    checksum = canonical_matrix_sha256(reference.values)

    elapsed: list[float] = []
    identical = 0
    for _ in range(args.runs):
        started = time.perf_counter()
        run = execute(recipe, bars)
        elapsed.append((time.perf_counter() - started) * 1000.0)
        # Bit-for-bit over canonical bytes: NaN cells included, so this
        # is stronger than an element compare that forgives NaN.
        if canonical_matrix_sha256(run.values) == checksum:
            identical += 1
        if run.recipe_hash != reference.recipe_hash:
            print("FAIL: recipe hash changed between runs", file=sys.stderr)
            return 1

    rows, features = reference.shape
    nan_total = int(np.isnan(reference.values).sum())

    print("HARSH QUANT OS feature benchmark (measured now, not a forecast)")
    print(f"dataset:         {bars.name}")
    print(f"dataset version: {bars.version}")
    print(f"rows x features: {rows} x {features}  (NaN cells: {nan_total})")
    print(f"recipe hash:     {recipe.recipe_hash()}")
    print(f"matrix sha256:   {checksum}")
    print(f"cold run:        {cold_ms:.3f} ms")
    print(
        f"warm runs ({args.runs}):  min {min(elapsed):.3f} ms, "
        f"median {statistics.median(elapsed):.3f} ms, max {max(elapsed):.3f} ms"
    )
    print(f"reproduced:      {identical}/{args.runs} runs sha256-identical to the cold run")
    print(f"python:          {sys.version.split()[0]} on {platform.platform()}")
    print(f"numpy:           {np.__version__}")

    if args.save:
        store = FeatureStore(args.store)
        digest = store.save(recipe, reference)
        store.verify(digest)
        print(f"store entry:     {args.store / digest} (verified)")

    if identical != args.runs:
        print(
            f"FAIL: {args.runs - identical} of {args.runs} runs differed from the first",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except RecipeError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
