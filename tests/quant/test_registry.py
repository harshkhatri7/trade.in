"""Golden, property and validation tests for ``quant.registry``.

What these prove, against quant-engine.md §7's "reproducible feature
recipes with recorded versions":

- **reproduce-twice through disk** — execute, save, execute again, load:
  all three matrices are bit-identical, and re-saving the entry is a
  quiet success (the checksum matched), not a silent overwrite;
- **the catalogue refuses to lie** — an interrupted save is incomplete
  and named as such; an edited ``recipe.json`` no longer hashes to its
  directory; a modified ``values.npy`` fails its checksum; a
  determinism violation (same recipe, different matrix) is an error for
  *both* sides rather than an overwrite;
- **cross-checks need the pairing** — ``verify`` catches what a single
  file cannot contradict about itself (dataset pin, column order, NaN
  counts), because those live in ``meta.json`` next to the artefacts.

Every store lives under ``tmp_path``: the suite never reads or writes
``data/``, so a fresh clone passes identically.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import numpy as np
import pytest

from harsh_quant_os.quant.recipes import (
    BarBatch,
    DatasetRef,
    FeatureMatrix,
    FeatureRecipe,
    FeatureSpec,
    RecipeError,
    execute,
)
from harsh_quant_os.quant.registry import (
    FeatureStore,
    canonical_matrix_sha256,
    canonical_times_sha256,
)

pytestmark = pytest.mark.quant

VERSION = "1234567890abcdef" * 4
OTHER_VERSION = "fedcba9876543210" * 4


def _batch(version: str = VERSION) -> BarBatch:
    """A five-bar synthetic batch with exactly dyadic returns."""
    return BarBatch(
        name="kraken.xbtusd.1m",
        version=version,
        time=np.arange(5, dtype=np.int64) * 60,
        open=np.array([100.0, 150.0, 75.0, 150.0, 100.0]),
        high=np.array([110.0, 160.0, 85.0, 160.0, 110.0]),
        low=np.array([90.0, 140.0, 65.0, 140.0, 90.0]),
        close=np.array([100.0, 150.0, 75.0, 150.0, 100.0]),
        volume=np.array([10.0, 20.0, 30.0, 40.0, 50.0]),
    )


def _recipe(version: str = VERSION) -> FeatureRecipe:
    """The three-feature recipe used throughout."""
    return FeatureRecipe(
        recipe_version=1,
        inputs=(DatasetRef(dataset_id="kraken.xbtusd.1m", version=version),),
        features=(
            FeatureSpec(name="sma_2", op="sma", source="close", params={"window": 2}),
            FeatureSpec(name="log_ret", op="log_returns", source="close"),
            FeatureSpec(name="lag_1", op="lag", source="close", params={"periods": 1}),
        ),
        nan_policy="warm-up NaN retained; rows never dropped",
    )


def _save_one(store: FeatureStore, version: str = VERSION) -> tuple[FeatureRecipe, FeatureMatrix]:
    """Execute and save the standard recipe; return both halves."""
    recipe = _recipe(version)
    matrix = execute(recipe, _batch(version))
    store.save(recipe, matrix)
    return recipe, matrix


# ---------------------------------------------------------------------------
# Round trip and reproduce-twice
# ---------------------------------------------------------------------------


def test_save_then_load_round_trips_everything(tmp_path: Path) -> None:
    store = FeatureStore(tmp_path / "features")
    recipe = _recipe()
    matrix = execute(recipe, _batch())

    digest = store.save(recipe, matrix)
    assert digest == recipe.recipe_hash()
    assert store.list() == (digest,)

    assert store.load_recipe(digest) == recipe
    loaded = store.load_matrix(digest)
    np.testing.assert_array_equal(loaded.values, matrix.values)
    np.testing.assert_array_equal(loaded.row_times, matrix.row_times)
    assert loaded.columns == matrix.columns
    assert loaded.recipe_hash == matrix.recipe_hash
    assert loaded.dataset_id == matrix.dataset_id
    assert loaded.dataset_version == matrix.dataset_version
    store.verify(digest)  # silence means consistent


def test_reproduce_twice_through_disk_is_bit_identical(tmp_path: Path) -> None:
    store = FeatureStore(tmp_path / "features")
    recipe = _recipe()

    first_run = execute(recipe, _batch())
    store.save(recipe, first_run)
    second_run = execute(recipe, _batch())  # a fresh execution
    store.save(recipe, second_run)  # checksum matches: quiet success
    from_disk = store.load_matrix(recipe.recipe_hash())

    np.testing.assert_array_equal(first_run.values, second_run.values)
    np.testing.assert_array_equal(second_run.values, from_disk.values)
    assert canonical_matrix_sha256(from_disk.values) == canonical_matrix_sha256(first_run.values)


def test_record_bytes_are_identical_across_roots(tmp_path: Path) -> None:
    recipe = _recipe()
    matrix = execute(recipe, _batch())
    first = tmp_path / "a"
    second = tmp_path / "b"
    FeatureStore(first).save(recipe, matrix)
    FeatureStore(second).save(recipe, matrix)
    entry = recipe.recipe_hash()
    assert (first / entry / "recipe.json").read_bytes() == (
        second / entry / "recipe.json"
    ).read_bytes()
    assert (first / entry / "meta.json").read_bytes() == (second / entry / "meta.json").read_bytes()


def test_meta_records_the_pinned_version_and_nan_counts(tmp_path: Path) -> None:
    store = FeatureStore(tmp_path / "features")
    recipe, _ = _save_one(store)
    meta = json.loads(
        (tmp_path / "features" / recipe.recipe_hash() / "meta.json").read_text("utf-8")
    )
    assert meta["dataset_id"] == "kraken.xbtusd.1m"
    assert meta["dataset_version"] == VERSION
    assert meta["columns"] == ["sma_2", "log_ret", "lag_1"]
    assert meta["rows"] == 5
    assert meta["nan_counts"] == [1, 1, 1]
    assert meta["recipe_version"] == 1


# ---------------------------------------------------------------------------
# Refusals: wrong matrix, determinism, tampering, incompleteness
# ---------------------------------------------------------------------------


def test_save_refuses_a_matrix_produced_by_a_different_recipe(tmp_path: Path) -> None:
    store = FeatureStore(tmp_path / "features")
    other_recipe = FeatureRecipe(
        recipe_version=1,
        inputs=(DatasetRef(dataset_id="kraken.xbtusd.1m", version=VERSION),),
        features=(FeatureSpec(name="sma_5", op="sma", source="close", params={"window": 5}),),
        nan_policy="warm-up NaN retained; rows never dropped",
    )
    foreign = execute(other_recipe, _batch())
    with pytest.raises(RecipeError, match="refusing to file it under the wrong recipe"):
        store.save(_recipe(), foreign)


def test_save_refuses_a_matrix_whose_dataset_does_not_match_the_pin(tmp_path: Path) -> None:
    store = FeatureStore(tmp_path / "features")
    matrix = execute(_recipe(), _batch())
    drifted = dataclasses.replace(matrix, dataset_version="e" * 64)
    with pytest.raises(RecipeError, match="recipe pins"):
        store.save(_recipe(), drifted)


def test_save_refuses_a_determinism_violation_instead_of_overwriting(tmp_path: Path) -> None:
    store = FeatureStore(tmp_path / "features")
    recipe = _recipe()
    matrix = execute(recipe, _batch())
    store.save(recipe, matrix)

    altered_values = matrix.values.copy()
    altered_values[1, 0] += 1.0  # same recipe, different numbers
    altered = dataclasses.replace(matrix, values=altered_values)
    with pytest.raises(RecipeError, match="determinism violation"):
        store.save(recipe, altered)
    # The original entry is untouched: the refusal changed nothing.
    np.testing.assert_array_equal(store.load_matrix(recipe.recipe_hash()).values, matrix.values)


def test_an_edited_recipe_is_refused_because_it_no_longer_hashes_to_its_entry(
    tmp_path: Path,
) -> None:
    store = FeatureStore(tmp_path / "features")
    recipe, _ = _save_one(store)
    entry = tmp_path / "features" / recipe.recipe_hash()

    edited = json.loads(entry.joinpath("recipe.json").read_text("utf-8"))
    edited["features"][0]["params"]["window"] = 3  # still valid JSON, different recipe
    entry.joinpath("recipe.json").write_text(json.dumps(edited), encoding="utf-8")
    with pytest.raises(RecipeError, match="modified after it was filed"):
        store.load_recipe(recipe.recipe_hash())
    with pytest.raises(RecipeError, match="modified after it was filed"):
        store.verify(recipe.recipe_hash())

    entry.joinpath("recipe.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(RecipeError, match="not valid JSON"):
        store.load_recipe(recipe.recipe_hash())


def test_a_modified_matrix_is_refused_by_its_checksum(tmp_path: Path) -> None:
    store = FeatureStore(tmp_path / "features")
    recipe, matrix = _save_one(store)
    entry = tmp_path / "features" / recipe.recipe_hash()

    tampered = matrix.values.copy()
    tampered[2, 1] = 12345.0
    np.save(entry / "values.npy", tampered)
    with pytest.raises(RecipeError, match="does not match its recorded checksum"):
        store.load_matrix(recipe.recipe_hash())
    with pytest.raises(RecipeError, match="does not match its recorded checksum"):
        store.verify(recipe.recipe_hash())


def test_modified_meta_fields_are_caught_by_the_pairing_check(tmp_path: Path) -> None:
    store = FeatureStore(tmp_path / "features")
    recipe, _ = _save_one(store)
    meta_path = tmp_path / "features" / recipe.recipe_hash() / "meta.json"

    # A wrong checksum in meta: the artefact is fine, the record is not.
    meta = json.loads(meta_path.read_text("utf-8"))
    meta["matrix_sha256"] = "a" * 64
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(RecipeError, match="does not match its recorded checksum"):
        store.load_matrix(recipe.recipe_hash())

    # Re-restore the checksum, then falsify only the recorded dataset
    # version: load_matrix cannot know, verify can — the recipe pins it.
    meta = json.loads(meta_path.read_text("utf-8"))
    matrix = execute(recipe, _batch())
    meta["matrix_sha256"] = canonical_matrix_sha256(matrix.values)
    meta["dataset_version"] = "b" * 64
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    store.load_matrix(recipe.recipe_hash())  # structurally fine on its own
    with pytest.raises(RecipeError, match="recipe pins"):
        store.verify(recipe.recipe_hash())

    # Column order is likewise only checkable against the recipe.
    meta = json.loads(meta_path.read_text("utf-8"))
    meta["dataset_version"] = VERSION
    meta["columns"] = ["log_ret", "sma_2", "lag_1"]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(RecipeError, match="stores columns"):
        store.verify(recipe.recipe_hash())


def test_an_interrupted_save_is_incomplete_refused_and_repairable(tmp_path: Path) -> None:
    store = FeatureStore(tmp_path / "features")
    recipe, _ = _save_one(store)
    entry = tmp_path / "features" / recipe.recipe_hash()
    entry.joinpath("meta.json").unlink()  # simulate dying before the marker

    assert store.list() == ()  # not listed as complete
    with pytest.raises(RecipeError, match=re.escape("incomplete: missing meta.json")):
        store.load_recipe(recipe.recipe_hash())
    with pytest.raises(RecipeError, match="incomplete"):
        store.verify(recipe.recipe_hash())

    store.save(recipe, execute(recipe, _batch()))  # re-save repairs
    assert store.list() == (recipe.recipe_hash(),)
    store.verify(recipe.recipe_hash())


def test_unknown_and_malformed_hashes_are_refused(tmp_path: Path) -> None:
    store = FeatureStore(tmp_path / "features")
    with pytest.raises(RecipeError, match="not a recipe hash"):
        store.load_recipe("nope")
    with pytest.raises(RecipeError, match="no feature set recorded"):
        store.load_matrix("f" * 64)
    with pytest.raises(RecipeError, match="not a recipe hash"):
        store.verify("UPPER" + "0" * 59)


# ---------------------------------------------------------------------------
# Listing and isolation
# ---------------------------------------------------------------------------


def test_listing_skips_non_entries_and_orders_hashes(tmp_path: Path) -> None:
    root = tmp_path / "features"
    store = FeatureStore(root)
    assert store.list() == ()  # a missing root is empty, not an error

    root.mkdir(parents=True)
    (root / ".gitkeep").write_text("", encoding="utf-8")
    (root / "not-a-hash").mkdir()
    assert store.list() == ()

    first = _recipe()
    store.save(first, execute(first, _batch()))
    other = FeatureRecipe(
        recipe_version=1,
        inputs=(DatasetRef(dataset_id="kraken.xbtusd.1m", version=VERSION),),
        features=(FeatureSpec(name="sma_5", op="sma", source="close", params={"window": 5}),),
        nan_policy="warm-up NaN retained; rows never dropped",
    )
    store.save(other, execute(other, _batch()))
    expected = tuple(sorted([first.recipe_hash(), other.recipe_hash()]))
    assert store.list() == expected


def test_loaded_arrays_are_isolated_from_the_store_and_vice_versa(
    tmp_path: Path,
) -> None:
    store = FeatureStore(tmp_path / "features")
    recipe, matrix = _save_one(store)

    loaded = store.load_matrix(recipe.recipe_hash())
    loaded.values[0, 0] = -999.0  # mutating the loaded copy...
    np.testing.assert_array_equal(  # ...changes nothing on disk
        store.load_matrix(recipe.recipe_hash()).values, matrix.values
    )


def test_save_does_not_mutate_its_inputs(tmp_path: Path) -> None:
    store = FeatureStore(tmp_path / "features")
    recipe = _recipe()
    matrix = execute(recipe, _batch())
    recipe_before = recipe.canonical_json()
    values_before = matrix.values.copy()
    times_before = matrix.row_times.copy()

    store.save(recipe, matrix)
    assert recipe.canonical_json() == recipe_before
    np.testing.assert_array_equal(matrix.values, values_before)
    np.testing.assert_array_equal(matrix.row_times, times_before)


# ---------------------------------------------------------------------------
# Canonical checksums
# ---------------------------------------------------------------------------


def test_canonical_checksums_ignore_memory_layout_not_content() -> None:
    values = np.arange(12, dtype=np.float64).reshape(3, 4)
    assert canonical_matrix_sha256(values) == canonical_matrix_sha256(np.asfortranarray(values))
    assert canonical_matrix_sha256(values) != canonical_matrix_sha256(values + 1)
    times = np.arange(5, dtype=np.int64)
    assert canonical_times_sha256(times) == canonical_times_sha256(times.copy())
    assert canonical_times_sha256(times) != canonical_times_sha256(times + 1)
