"""Golden, property and validation tests for ``quant.recipes``.

The exit criteria these pin down (quant-engine.md §7):

- **reproducibility** — the canonical JSON is compared against a string
  written out here byte for byte, the recipe hash is SHA-256 over
  *those* bytes recomputed with hashlib, and two executions of the same
  recipe on the same batch are bit-identical;
- **recorded versions** — a recipe pinned to one dataset version refuses
  a batch from another, naming both sides;
- **integrity of the loader** — ``load_bar_batch`` re-hashes the clean
  artefact against its content-addressed directory, refuses missing
  volume instead of filling it, and refuses path tricks in names.

The store fixture is written into ``tmp_path`` in the exact CSV layout
``_bars_to_csv`` produces (header, one line per bar, ``\\n``), so the
tests never depend on ``data/`` existing — a fresh clone must pass.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from harsh_quant_os.quant.indicators import ema, sma
from harsh_quant_os.quant.recipes import (
    BarBatch,
    DatasetRef,
    FeatureMatrix,
    FeatureRecipe,
    FeatureSpec,
    RecipeError,
    execute,
    load_bar_batch,
)
from harsh_quant_os.quant.series import InvalidSeries

pytestmark = pytest.mark.quant

#: A fixed stand-in version: 64 lowercase hex characters, like a real
#: content-addressed artefact hash. Synthetic fixtures, never presented
#: as data from anywhere.
VERSION = "1234567890abcdef" * 4

CSV_HEADER = "symbol,timeframe,timestamp,open,high,low,close,volume"


def _batch(**overrides: Any) -> BarBatch:
    """A five-bar batch; close chosen so returns are exactly dyadic."""
    values: dict[str, Any] = {
        "name": "kraken.xbtusd.1m",
        "version": VERSION,
        "time": np.arange(5, dtype=np.int64) * 60,
        "open": np.array([100.0, 150.0, 75.0, 150.0, 100.0]),
        "high": np.array([110.0, 160.0, 85.0, 160.0, 110.0]),
        "low": np.array([90.0, 140.0, 65.0, 140.0, 90.0]),
        "close": np.array([100.0, 150.0, 75.0, 150.0, 100.0]),
        "volume": np.array([10.0, 20.0, 30.0, 40.0, 50.0]),
    }
    values.update(overrides)
    return BarBatch(**values)


def _recipe(**overrides: Any) -> FeatureRecipe:
    """A three-feature recipe over the close column."""
    values: dict[str, Any] = {
        "recipe_version": 1,
        "inputs": (DatasetRef(dataset_id="kraken.xbtusd.1m", version=VERSION),),
        "features": (
            FeatureSpec(name="sma_2", op="sma", source="close", params={"window": 2}),
            FeatureSpec(name="log_ret", op="log_returns", source="close"),
            FeatureSpec(name="lag_1", op="lag", source="close", params={"periods": 1}),
        ),
        "nan_policy": "warm-up NaN retained; rows never dropped",
    }
    values.update(overrides)
    return FeatureRecipe(**values)


def _payload() -> dict[str, Any]:
    """A valid JSON payload for mutation-based refusals."""
    return {
        "recipe_version": 1,
        "inputs": [{"dataset_id": "kraken.xbtusd.1m", "version": VERSION}],
        "features": [{"name": "sma_2", "op": "sma", "source": "close", "params": {"window": 2}}],
        "nan_policy": "warm-up NaN retained; rows never dropped",
    }


def _csv_bytes(rows: Sequence[str]) -> bytes:
    """The exact byte layout ``_bars_to_csv`` writes (``\\n``-separated)."""
    return ("\n".join([CSV_HEADER, *rows, ""])).encode("utf-8")


def _write_store(root: Path, name: str, payload: bytes, *, dirname: str | None = None) -> Path:
    """Write one version directory of a dataset and return its directory."""
    digest = dirname if dirname is not None else hashlib.sha256(payload).hexdigest()
    directory = root / "clean" / name / digest
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "bars.csv").write_bytes(payload)
    return directory


GOOD_ROWS = (
    "XBTUSD,1m,2024-01-01T00:00:00+00:00,100,110,90,105,10",
    "XBTUSD,1m,2024-01-01T00:01:00+00:00,105,115,100,110,12",
    "XBTUSD,1m,2024-01-01T00:02:00+00:00,110,120,105,115,14",
)

# ---------------------------------------------------------------------------
# Recipe schema, canonical form, hash
# ---------------------------------------------------------------------------


def test_canonical_json_matches_the_string_written_out_here() -> None:
    # Hand-assembled: keys in sorted order (features, inputs, nan_policy,
    # recipe_version; name, op, params, source), no whitespace. The hash
    # must be SHA-256 of exactly these bytes, so it is recomputed here
    # with hashlib over the string above rather than over the object.
    expected = (
        '{"features":[{"name":"sma_2","op":"sma","params":{"window":2},"source":"close"}],'
        f'"inputs":[{{"dataset_id":"kraken.xbtusd.1m","version":"{VERSION}"}}],'
        '"nan_policy":"warm-up NaN retained; rows never dropped",'
        '"recipe_version":1}'
    )
    payload = _payload()
    payload["features"] = [
        {"name": "sma_2", "op": "sma", "source": "close", "params": {"window": 2}}
    ]
    payload["inputs"] = [{"dataset_id": "kraken.xbtusd.1m", "version": VERSION}]
    recipe = FeatureRecipe.from_json(json.dumps(payload))
    assert recipe.canonical_json() == expected
    assert recipe.recipe_hash() == hashlib.sha256(expected.encode("utf-8")).hexdigest()


def test_any_meaningful_change_changes_the_hash() -> None:
    base = _recipe()
    variants = [
        base,
        _recipe(nan_policy="warm-up NaN retained; rows dropped where NaN"),
        _recipe(
            features=(
                FeatureSpec(name="sma_2", op="sma", source="close", params={"window": 3}),
                *base.features[1:],
            )
        ),
        _recipe(
            features=(
                *base.features[:2],
                FeatureSpec(name="lag_2", op="lag", source="close", params={"periods": 2}),
            )
        ),
    ]
    hashes = [variant.recipe_hash() for variant in variants]
    assert len(set(hashes)) == len(hashes)


def test_recipe_json_round_trips_through_from_json() -> None:
    original = _recipe()
    assert FeatureRecipe.from_json(original.to_json()) == original


def test_construction_copies_params_so_the_hash_cannot_drift() -> None:
    params = {"window": 2}
    feature = FeatureSpec(name="sma_2", op="sma", source="close", params=params)
    params["window"] = 99  # the caller's dict, not the recipe's
    assert feature.params == {"window": 2}
    # The recipe built from that feature hashes exactly like the base one.
    rebuilt = _recipe(features=(feature, *_recipe().features[1:]))
    assert rebuilt.recipe_hash() == _recipe().recipe_hash()


# ---------------------------------------------------------------------------
# from_json refusals (mutation-based)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda p: p.update(recipe_version=2), "not supported"),
        (lambda p: p.update(recipe_version="1"), "must be an integer"),
        (lambda p: p.update(inputs=[]), "exactly one input"),
        (lambda p: p.update(features=[]), "at least one feature"),
        (lambda p: p.update(nan_policy="   "), "nan_policy"),
        (lambda p: p.update(extra=True), "unknown field"),
        (lambda p: p.pop("nan_policy"), "missing field"),
        (lambda p: p["inputs"][0].update(version="short"), "64-character"),
        (lambda p: p["inputs"][0].update(dataset_id=""), "must not be empty"),
        (lambda p: p["inputs"][0].update(source="x"), "unknown field"),
        (lambda p: p["features"][0].update(op="telepathy"), "unknown op"),
        (lambda p: p["features"][0].update(params={}), "missing parameter"),
        (
            lambda p: p["features"][0].update(params={"window": 2, "extra": 1}),
            "unexpected parameter",
        ),
        # bool is an int subclass in JSON-typed values: refused at the
        # typing layer, before the range check even runs.
        (lambda p: p["features"][0].update(params={"window": True}), "must be an integer"),
        (lambda p: p["features"][0].update(params={"window": 0}), "integer >= 1"),
        (lambda p: p["features"][0].update(name="close"), "shadow"),
        (lambda p: p["features"][0].update(name=""), "feature name"),
        (
            lambda p: p["features"][0].update(source="volume_flow"),
            "neither an input column nor an earlier feature",
        ),
        (lambda p: p["features"].append(dict(p["features"][0])), "duplicate feature name"),
        (lambda p: p["features"][0].update(params="window"), "params must be a JSON object"),
        (lambda p: p.update(inputs={"dataset_id": "x"}), "inputs must be a JSON array"),
        (lambda p: p.update(features="sma"), "features must be a JSON array"),
    ],
)
def test_from_json_refuses_invalid_payloads(
    mutate: Callable[[dict[str, Any]], None], match: str
) -> None:
    payload = _payload()
    mutate(payload)
    with pytest.raises(RecipeError, match=match):
        FeatureRecipe.from_json(json.dumps(payload))


def test_from_json_requires_json_text_and_an_object() -> None:
    with pytest.raises(RecipeError, match="not valid JSON"):
        FeatureRecipe.from_json("{nope")
    with pytest.raises(RecipeError, match="must be a JSON object"):
        FeatureRecipe.from_json("[1, 2]")


def test_from_json_refuses_a_forward_reference() -> None:
    # The second feature reads the first — but the first is declared
    # after it, so at execution time the source would not exist yet.
    payload = _payload()
    payload["features"] = [
        {"name": "derived", "op": "lag", "source": "sma_2", "params": {"periods": 1}},
        {"name": "sma_2", "op": "sma", "source": "close", "params": {"window": 2}},
    ]
    with pytest.raises(RecipeError, match="neither an input column nor an earlier feature"):
        FeatureRecipe.from_json(json.dumps(payload))


def test_a_recipe_may_read_an_earlier_feature() -> None:
    payload = _payload()
    payload["features"] = [
        {"name": "sma_2", "op": "sma", "source": "close", "params": {"window": 2}},
        {"name": "sma_of_sma", "op": "sma", "source": "sma_2", "params": {"window": 2}},
    ]
    recipe = FeatureRecipe.from_json(json.dumps(payload))
    assert recipe.features[1].source == "sma_2"


def test_execute_chains_primitives_in_declaration_order() -> None:
    # ema (first-value seeded) is finite from row 0, so it can feed the
    # next primitive; the composition must equal applying the same
    # primitives one after the other (each one itself golden-tested in
    # test_indicators).
    recipe = _recipe(
        features=(
            FeatureSpec(name="ema_3", op="ema", source="close", params={"span": 3}),
            FeatureSpec(name="sma_2_ema", op="sma", source="ema_3", params={"window": 2}),
        )
    )
    matrix = execute(recipe, _batch())
    expected_ema = ema(_batch().close, 3)
    expected_sma = sma(expected_ema, 2)
    np.testing.assert_array_equal(matrix.values[:, 0], expected_ema)
    np.testing.assert_array_equal(matrix.values[:, 1], expected_sma)
    assert np.isfinite(matrix.values[:, 0]).all()
    assert np.isnan(matrix.values[0, 1])  # the chained sma's own warm-up


def test_execute_refuses_a_chained_source_carrying_warmup_nan() -> None:
    # sma_2's warm-up NaN must not slide into the next primitive: an
    # undefined region is not data, and the refusal names the feature
    # and the row instead of an index into an unnamed array.
    recipe = _recipe(
        features=(
            FeatureSpec(name="sma_2", op="sma", source="close", params={"window": 2}),
            FeatureSpec(name="after_sma", op="lag", source="sma_2", params={"periods": 1}),
        )
    )
    with pytest.raises(InvalidSeries, match=r"'after_sma' reads 'sma_2'.*row 0"):
        execute(recipe, _batch())


def test_feature_spec_validates_locally_at_construction() -> None:
    with pytest.raises(RecipeError, match="unknown op"):
        FeatureSpec(name="x", op="nope", source="close")
    with pytest.raises(RecipeError, match="missing parameter"):
        FeatureSpec(name="x", op="sma", source="close")
    with pytest.raises(RecipeError, match="shadow"):
        FeatureSpec(name="volume", op="log_returns", source="close")


# ---------------------------------------------------------------------------
# Execution: golden matrix, determinism, pins
# ---------------------------------------------------------------------------


def test_execute_golden_matrix_from_hand_computed_values() -> None:
    matrix = execute(_recipe(), _batch())
    assert matrix.shape == (5, 3)
    assert matrix.columns == ("sma_2", "log_ret", "lag_1")
    # sma_2 of [100,150,75,150,100]: [NaN, 125, 112.5, 112.5, 125] — exact.
    np.testing.assert_array_equal(
        matrix.values[:, 0], np.array([np.nan, 125.0, 112.5, 112.5, 125.0])
    )
    # log returns: ln(150/100), ln(75/150), ln(150/75), ln(100/150) — the
    # definition applied per element, not via the implementation.
    np.testing.assert_allclose(
        matrix.values[:, 1],
        np.array([np.nan, np.log(1.5), np.log(0.5), np.log(2.0), np.log(100 / 150)]),
        rtol=1e-15,
        atol=0,
    )
    # lag_1: [NaN, 100, 150, 75, 150] — exact.
    np.testing.assert_array_equal(
        matrix.values[:, 2], np.array([np.nan, 100.0, 150.0, 75.0, 150.0])
    )
    np.testing.assert_array_equal(matrix.row_times, _batch().time)
    assert matrix.recipe_hash == _recipe().recipe_hash()
    assert matrix.dataset_id == "kraken.xbtusd.1m"
    assert matrix.dataset_version == VERSION
    assert matrix.nan_counts() == (1, 1, 1)


def test_execute_is_bit_identical_and_leaves_the_batch_alone() -> None:
    batch = _batch()
    untouched = {
        label: getattr(batch, label).copy()
        for label in ("time", "open", "high", "low", "close", "volume")
    }
    first = execute(_recipe(), batch)
    second = execute(_recipe(), batch)
    np.testing.assert_array_equal(first.values, second.values)
    assert first.recipe_hash == second.recipe_hash
    for label, original in untouched.items():
        np.testing.assert_array_equal(getattr(batch, label), original)


def test_execute_refuses_a_different_dataset_version_naming_both_sides() -> None:
    other = _batch(version="b" * 64)
    with pytest.raises(RecipeError, match=re.escape("pinned to kraken.xbtusd.1m version")):
        execute(_recipe(), other)
    with pytest.raises(RecipeError, match=f"bars are version {'b' * 64}"):
        execute(_recipe(), other)


def test_execute_refuses_a_different_dataset_name() -> None:
    with pytest.raises(RecipeError, match="refusing to compute on different data"):
        execute(_recipe(), _batch(name="kraken.xbtusd.1d"))


def test_execute_validates_a_hand_built_recipe_every_time() -> None:
    # Bypasses from_json entirely — validate() still runs.
    hand_built = _recipe(
        features=(
            FeatureSpec(name="derived", op="lag", source="sma_2", params={"periods": 1}),
            FeatureSpec(name="sma_2", op="sma", source="close", params={"window": 2}),
        )
    )
    with pytest.raises(RecipeError, match="neither an input column nor an earlier feature"):
        execute(hand_built, _batch())


def test_execute_surfaces_a_primitive_refusal_through_the_recipe() -> None:
    # close contains 0: the log-return primitive refuses, and the
    # refusal travels up unchanged instead of becoming -inf.
    batch = _batch(close=np.array([100.0, 0.0, 75.0, 150.0, 100.0]))
    recipe = _recipe(features=(FeatureSpec(name="log_ret", op="log_returns", source="close"),))
    with pytest.raises(InvalidSeries, match="strictly positive"):
        execute(recipe, batch)


def test_feature_matrix_is_validated_and_isolated_from_its_inputs() -> None:
    values = np.ones((3, 1))
    times = np.arange(3, dtype=np.int64)
    matrix = FeatureMatrix(
        values=values,
        columns=("a",),
        row_times=times,
        recipe_hash=VERSION,
        dataset_id="d",
        dataset_version=VERSION,
    )
    values[0, 0] = 99.0  # constructing copied; the original is not the matrix's
    times[0] = -1
    assert matrix.values[0, 0] == 1.0
    assert matrix.row_times[0] == 0
    with pytest.raises(InvalidSeries, match="rows but row_times"):
        FeatureMatrix(
            values=np.ones((2, 1)),
            columns=("a",),
            row_times=np.arange(3, dtype=np.int64),
            recipe_hash=VERSION,
            dataset_id="d",
            dataset_version=VERSION,
        )
    with pytest.raises(InvalidSeries, match="columns but"):
        FeatureMatrix(
            values=np.ones((3, 2)),
            columns=("a",),
            row_times=np.arange(3, dtype=np.int64),
            recipe_hash=VERSION,
            dataset_id="d",
            dataset_version=VERSION,
        )
    with pytest.raises(InvalidSeries, match="recipe_hash"):
        FeatureMatrix(
            values=np.ones((3, 1)),
            columns=("a",),
            row_times=np.arange(3, dtype=np.int64),
            recipe_hash="short",
            dataset_id="d",
            dataset_version=VERSION,
        )


# ---------------------------------------------------------------------------
# BarBatch boundary
# ---------------------------------------------------------------------------


def test_bar_batch_rejects_misaligned_or_invalid_columns() -> None:
    with pytest.raises(InvalidSeries, match="same length"):
        _batch(volume=np.ones(4))
    with pytest.raises(InvalidSeries, match="at least one bar"):
        _batch(
            time=np.array([], dtype=np.int64),
            open=np.array([]),
            high=np.array([]),
            low=np.array([]),
            close=np.array([]),
            volume=np.array([]),
        )
    with pytest.raises(InvalidSeries, match="must strictly increase"):
        _batch(time=np.array([0, 60, 60, 180, 240], dtype=np.int64))
    with pytest.raises(InvalidSeries, match="non-finite value at row 2"):
        _batch(close=np.array([100.0, 150.0, np.nan, 150.0, 100.0]))
    with pytest.raises(InvalidSeries, match="negative value at row 1"):
        _batch(volume=np.array([10.0, -1.0, 30.0, 40.0, 50.0]))
    with pytest.raises(InvalidSeries, match="64-character"):
        _batch(version="not-a-hash")
    with pytest.raises(InvalidSeries, match="must not be empty"):
        _batch(name="  ")


def test_bar_batch_column_lookup() -> None:
    batch = _batch()
    np.testing.assert_array_equal(batch.column("close"), batch.close)
    with pytest.raises(InvalidSeries, match="not a batch column"):
        batch.column("adj_close")


# ---------------------------------------------------------------------------
# load_bar_batch against a written store fixture
# ---------------------------------------------------------------------------


def test_load_bar_batch_reads_a_stored_version_and_recomputes_its_hash(tmp_path: Path) -> None:
    payload = _csv_bytes(GOOD_ROWS)
    written = _write_store(tmp_path, "kraken.xbtusd.1m", payload)
    batch = load_bar_batch(tmp_path, "kraken.xbtusd.1m")
    # The version IS the SHA-256 of the bytes on disk, recomputed here.
    assert batch.version == hashlib.sha256(payload).hexdigest() == written.name
    assert batch.name == "kraken.xbtusd.1m"
    np.testing.assert_array_equal(batch.close, np.array([105.0, 110.0, 115.0]))
    np.testing.assert_array_equal(batch.volume, np.array([10.0, 12.0, 14.0]))
    np.testing.assert_array_equal(
        batch.time, np.array([1704067200, 1704067260, 1704067320], dtype=np.int64)
    )


def test_load_bar_batch_requires_a_version_when_several_exist(tmp_path: Path) -> None:
    first = _csv_bytes(GOOD_ROWS)
    second = _csv_bytes((*GOOD_ROWS, "XBTUSD,1m,2024-01-01T00:03:00+00:00,115,125,110,120,16"))
    _write_store(tmp_path, "kraken.xbtusd.1m", first)
    _write_store(tmp_path, "kraken.xbtusd.1m", second)
    with pytest.raises(RecipeError, match="pass version= to choose one"):
        load_bar_batch(tmp_path, "kraken.xbtusd.1m")
    chosen = load_bar_batch(
        tmp_path, "kraken.xbtusd.1m", version=hashlib.sha256(second).hexdigest()
    )
    assert chosen.close.size == 4
    with pytest.raises(RecipeError, match="has no version"):
        load_bar_batch(tmp_path, "kraken.xbtusd.1m", version="c" * 64)


def test_load_bar_batch_refuses_an_artefact_that_does_not_match_its_directory(
    tmp_path: Path,
) -> None:
    payload = _csv_bytes(GOOD_ROWS)
    _write_store(tmp_path, "kraken.xbtusd.1m", payload, dirname="d" * 64)
    with pytest.raises(RecipeError, match="does not match its recorded version"):
        load_bar_batch(tmp_path, "kraken.xbtusd.1m")


def test_load_bar_batch_refuses_missing_volume_instead_of_filling_it(tmp_path: Path) -> None:
    rows = (
        "XBTUSD,1m,2024-01-01T00:00:00+00:00,100,110,90,105,10",
        "XBTUSD,1m,2024-01-01T00:01:00+00:00,105,115,100,110,",  # volume absent
        "XBTUSD,1m,2024-01-01T00:02:00+00:00,110,120,105,115,14",
    )
    _write_store(tmp_path, "kraken.xbtusd.1m", _csv_bytes(rows))
    with pytest.raises(RecipeError, match=r"1 of 3 bars.*have no volume"):
        load_bar_batch(tmp_path, "kraken.xbtusd.1m")


def test_load_bar_batch_refuses_unknown_names_and_escape_attempts(tmp_path: Path) -> None:
    with pytest.raises(RecipeError, match="no stored dataset"):
        load_bar_batch(tmp_path, "kraken.xbtusd.1m")
    with pytest.raises(RecipeError, match="plain directory name"):
        load_bar_batch(tmp_path, "../secrets")


def test_load_bar_batch_refuses_an_empty_artefact(tmp_path: Path) -> None:
    _write_store(tmp_path, "kraken.xbtusd.1m", _csv_bytes(()))
    with pytest.raises(RecipeError, match="contains no bars"):
        load_bar_batch(tmp_path, "kraken.xbtusd.1m")
