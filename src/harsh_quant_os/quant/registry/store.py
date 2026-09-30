"""The versioned feature catalogue: where executed recipes are filed.

quant-engine.md §5's ``registry/`` — a directory of *complete* entries,
each named by its recipe's hash and holding the four files that make it
auditable:

- ``recipe.json`` — the canonical recipe bytes (the hash's input);
- ``values.npy`` / ``times.npy`` — the matrix and its row times;
- ``meta.json`` — recipe hash, dataset identity, shape, per-column NaN
  counts, and SHA-256 checksums over the canonical bytes of both
  artefacts.

Two rules hold throughout:

1. **``meta.json`` is written last.** Its presence *is* the completion
   marker: an interrupted save leaves an incomplete directory that
   :meth:`FeatureStore.load_recipe`, :meth:`load_matrix` and
   :meth:`verify` refuse by name, and a re-run of
   :meth:`save <FeatureStore.save>` repairs it. Nothing silently reads
   a half-written entry as complete.
2. **Re-saving is a determinism check, not a convenience.** If an entry
   is already complete, ``save`` compares the incoming matrix's
   canonical checksum with the recorded one: equal means the recipe
   really is reproducible (return quietly), different means two runs of
   the same recipe disagreed — a :class:`RecipeError` for a
   determinism violation, never an overwrite that hides it.

Checksums are over canonical little-endian C-order bytes (not the
``.npy`` container), so they verify the data itself regardless of how
the file happens to be laid out. ``data/`` is git-ignored, so what
lands here stays local research state.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from harsh_quant_os.quant.recipes import FeatureMatrix, FeatureRecipe, RecipeError

__all__ = ["FeatureStore", "canonical_matrix_sha256", "canonical_times_sha256"]

_RECIPE_FILE = "recipe.json"
_META_FILE = "meta.json"
_VALUES_FILE = "values.npy"
_TIMES_FILE = "times.npy"
_ENTRY_FILES = (_META_FILE, _RECIPE_FILE, _VALUES_FILE, _TIMES_FILE)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_META_FIELDS = frozenset(
    {
        "recipe_hash",
        "recipe_version",
        "dataset_id",
        "dataset_version",
        "rows",
        "columns",
        "nan_counts",
        "matrix_sha256",
        "row_times_sha256",
    }
)


def canonical_matrix_sha256(values: NDArray[np.float64]) -> str:
    """SHA-256 over the matrix's canonical little-endian C-order bytes.

    Independent of the ``.npy`` container, so the checksum survives a
    different numpy layout and verifies the data itself.
    """
    canonical = np.ascontiguousarray(values, dtype="<f8")
    return hashlib.sha256(canonical.tobytes()).hexdigest()


def canonical_times_sha256(times: NDArray[np.int64]) -> str:
    """SHA-256 over the row times' canonical little-endian bytes."""
    canonical = np.ascontiguousarray(times, dtype="<i8")
    return hashlib.sha256(canonical.tobytes()).hexdigest()


def _write_bytes(path: Path, payload: bytes) -> None:
    """Publish a file only once it is complete (store.py's atomic rule)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _npy_bytes(array: NDArray[Any]) -> bytes:
    """Serialise an array to ``.npy`` bytes in memory."""
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return buffer.getvalue()


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    """Canonical JSON bytes: sorted keys, no redundant whitespace."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return text.encode("utf-8")


def _check_sha256(value: object, *, where: str) -> str:
    """Return ``value`` as a 64-hex string or raise."""
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise RecipeError(f"{where} must be a 64-character lowercase SHA-256, got {value!r}")
    return value


def _check_text(value: object, *, where: str) -> str:
    """Return ``value`` as a non-empty string or raise."""
    if not isinstance(value, str) or not value:
        raise RecipeError(f"{where} must be a non-empty string, got {value!r}")
    return value


class FeatureStore:
    """A directory of executed feature sets, keyed by recipe hash.

    Args:
        root: Where entries live (e.g. ``data/features``). Created on
            first save; a missing root lists as empty rather than
            erroring — nothing recorded is not a failure.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def save(self, recipe: FeatureRecipe, matrix: FeatureMatrix) -> str:
        """File one executed recipe, checking reproducibility on the way.

        Args:
            recipe: The recipe that produced ``matrix`` (validated
                first).
            matrix: The execution result. Its ``recipe_hash`` must equal
                this recipe's, and its dataset identity must agree with
                the recipe's pin — the cross-check ``verify`` would do,
                done before anything is written.

        Returns:
            The recipe hash: the entry's directory name.

        Raises:
            RecipeError: Invalid recipe; a matrix from a different
            recipe; a recorded determinism violation (same recipe,
            different matrix checksum); or a mismatch between the
            matrix's dataset and the recipe's pin.
        """
        recipe.validate()
        digest = recipe.recipe_hash()
        if matrix.recipe_hash != digest:
            raise RecipeError(
                f"matrix carries recipe hash {matrix.recipe_hash} but this recipe hashes to "
                f"{digest}; refusing to file it under the wrong recipe"
            )
        reference = recipe.inputs[0]
        if matrix.dataset_id != reference.dataset_id:
            raise RecipeError(
                f"matrix was computed on dataset {matrix.dataset_id!r} but the recipe pins "
                f"{reference.dataset_id!r}"
            )
        if matrix.dataset_version != reference.version:
            raise RecipeError(
                f"matrix was computed on dataset version {matrix.dataset_version} but the "
                f"recipe pins {reference.version}"
            )

        checksum = canonical_matrix_sha256(matrix.values)
        times_checksum = canonical_times_sha256(matrix.row_times)
        entry = self._root / digest
        meta_path = entry / _META_FILE
        complete = all((entry / name).is_file() for name in _ENTRY_FILES)

        if meta_path.is_file():
            recorded = self._read_meta(meta_path, expect_hash=digest)
            if recorded["matrix_sha256"] != checksum:
                raise RecipeError(
                    f"determinism violation: recipe {digest} is already filed with matrix "
                    f"{str(recorded['matrix_sha256'])[:12]}... but this run produced "
                    f"{checksum[:12]}... — the same recipe on the same data must reproduce "
                    "the same matrix, so neither is filed over the other"
                )
            if complete:
                return digest
            # Complete meta, missing artefact files: an interrupted
            # repair. Rewrite the identical content below.

        _write_bytes(entry / _RECIPE_FILE, recipe.to_json().encode("utf-8"))
        _write_bytes(entry / _VALUES_FILE, _npy_bytes(matrix.values))
        _write_bytes(entry / _TIMES_FILE, _npy_bytes(matrix.row_times))
        meta: dict[str, Any] = {
            "recipe_hash": digest,
            "recipe_version": recipe.recipe_version,
            "dataset_id": reference.dataset_id,
            "dataset_version": reference.version,
            "rows": int(matrix.shape[0]),
            "columns": list(matrix.columns),
            "nan_counts": list(matrix.nan_counts()),
            "matrix_sha256": checksum,
            "row_times_sha256": times_checksum,
        }
        # Written last: its arrival is what makes the entry complete.
        _write_bytes(meta_path, _canonical_json_bytes(meta))
        return digest

    def load_recipe(self, recipe_hash: str) -> FeatureRecipe:
        """Read a filed recipe back and confirm it still hashes to its entry.

        Raises:
            RecipeError: Not a recipe hash; no such entry; the entry is
            incomplete; the file is not a valid recipe; or the file's
            canonical hash no longer equals the directory it sits in
            (it was edited after it was filed).
        """
        entry = self._require_entry(recipe_hash)
        path = entry / _RECIPE_FILE
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RecipeError(f"could not read {path}: {exc}") from exc
        recipe = FeatureRecipe.from_json(text)
        actual = recipe.recipe_hash()
        if actual != recipe_hash:
            raise RecipeError(
                f"stored recipe under {recipe_hash} actually hashes to {actual} — the file "
                "was modified after it was filed"
            )
        return recipe

    def load_matrix(self, recipe_hash: str) -> FeatureMatrix:
        """Read a filed matrix back, checksums verified first.

        Raises:
            RecipeError: Not a recipe hash; no such entry; the entry is
            incomplete; ``meta.json`` is malformed; a stored shape
            disagrees with the artefacts; or an artefact's bytes no
            longer hash to the checksum in ``meta.json`` (modified or
            corrupted after it was filed).
        """
        entry = self._require_entry(recipe_hash)
        meta = self._read_meta(entry / _META_FILE, expect_hash=recipe_hash)

        values = self._load_npy(entry / _VALUES_FILE, ndim=2)
        times = self._load_npy(entry / _TIMES_FILE, ndim=1)
        rows = meta["rows"]
        columns = meta["columns"]
        if values.shape != (rows, len(columns)):
            raise RecipeError(
                f"entry {recipe_hash} records a {rows}x{len(columns)} matrix but "
                f"{_VALUES_FILE} holds {values.shape}"
            )
        if times.shape != (rows,):
            raise RecipeError(
                f"entry {recipe_hash} records {rows} rows but {_TIMES_FILE} holds {times.shape}"
            )
        actual_values = canonical_matrix_sha256(values)
        if actual_values != meta["matrix_sha256"]:
            raise RecipeError(
                f"entry {recipe_hash}: stored matrix does not match its recorded checksum "
                f"(recorded {str(meta['matrix_sha256'])[:12]}..., file hashes to "
                f"{actual_values[:12]}...) — the artefact changed after it was filed"
            )
        actual_times = canonical_times_sha256(times)
        if actual_times != meta["row_times_sha256"]:
            raise RecipeError(
                f"entry {recipe_hash}: stored row times do not match their recorded checksum "
                f"(recorded {str(meta['row_times_sha256'])[:12]}..., file hashes to "
                f"{actual_times[:12]}...) — the artefact changed after it was filed"
            )

        return FeatureMatrix(
            values=values,
            columns=tuple(columns),
            row_times=times,
            recipe_hash=meta["recipe_hash"],
            dataset_id=meta["dataset_id"],
            dataset_version=meta["dataset_version"],
        )

    def list(self) -> tuple[str, ...]:
        """Every complete entry's recipe hash, sorted.

        Incomplete or unparseable directories are not returned (``.gitkeep``
        and friends are skipped by the hash-shaped name check); targeting
        one by name with :meth:`load_recipe`, :meth:`load_matrix` or
        :meth:`verify` surfaces exactly what is wrong with it. A missing
        root lists as empty.
        """
        if not self._root.is_dir():
            return ()
        hashes: list[str] = []
        for entry in sorted(self._root.iterdir()):
            if not entry.is_dir() or not _SHA256_RE.fullmatch(entry.name):
                continue
            meta_path = entry / _META_FILE
            if not meta_path.is_file():
                continue
            try:
                self._read_meta(meta_path, expect_hash=entry.name)
            except RecipeError:
                continue
            hashes.append(entry.name)
        return tuple(hashes)

    def verify(self, recipe_hash: str) -> None:
        """Cross-check a complete entry against its own recipe.

        Runs :meth:`load_recipe` and :meth:`load_matrix` (which verify
        internal consistency), then checks the parts only the pairing
        can show: the recorded dataset against the recipe's pin, the
        stored columns against the recipe's feature names, and the
        recorded per-column NaN counts against the artefact.

        Returns:
            None — success is silence.

        Raises:
            RecipeError: Any failed check, naming the field that
            disagrees.
        """
        recipe = self.load_recipe(recipe_hash)
        matrix = self.load_matrix(recipe_hash)
        meta = self._read_meta(self._root / recipe_hash / _META_FILE, expect_hash=recipe_hash)
        reference = recipe.inputs[0]
        if matrix.dataset_id != reference.dataset_id:
            raise RecipeError(
                f"entry {recipe_hash} records dataset {matrix.dataset_id!r} but the recipe "
                f"pins {reference.dataset_id!r}"
            )
        if matrix.dataset_version != reference.version:
            raise RecipeError(
                f"entry {recipe_hash} records dataset version {matrix.dataset_version} but the "
                f"recipe pins {reference.version}"
            )
        expected_columns = tuple(feature.name for feature in recipe.features)
        if matrix.columns != expected_columns:
            raise RecipeError(
                f"entry {recipe_hash} stores columns {matrix.columns} but the recipe produces "
                f"{expected_columns}"
            )
        expected_nans = list(matrix.nan_counts())
        if meta["nan_counts"] != expected_nans:
            raise RecipeError(
                f"entry {recipe_hash} records NaN counts {meta['nan_counts']} but the matrix "
                f"contains {expected_nans}"
            )

    def _require_entry(self, recipe_hash: str) -> Path:
        """Validate the hash format and the entry's completeness."""
        if not isinstance(recipe_hash, str) or not _SHA256_RE.fullmatch(recipe_hash):
            raise RecipeError(f"{recipe_hash!r} is not a recipe hash (64 lowercase hex characters)")
        entry = self._root / recipe_hash
        if not entry.is_dir():
            raise RecipeError(f"no feature set recorded under {entry}")
        missing = [name for name in _ENTRY_FILES if not (entry / name).is_file()]
        if missing:
            raise RecipeError(
                f"feature set {recipe_hash} is incomplete: missing {', '.join(missing)} — a "
                "save was interrupted; call save() again to repair it"
            )
        return entry

    def _read_meta(self, path: Path, *, expect_hash: str) -> dict[str, Any]:
        """Parse and structurally validate one ``meta.json``."""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RecipeError(f"{path} is not valid JSON: {exc}") from exc
        except OSError as exc:
            raise RecipeError(f"could not read {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise RecipeError(f"{path} must contain a JSON object, got {type(payload).__name__}")
        actual_fields = set(payload)
        unknown = actual_fields - _META_FIELDS
        if unknown:
            raise RecipeError(f"{path} has unknown field(s): {', '.join(sorted(unknown))}")
        missing = _META_FIELDS - actual_fields
        if missing:
            raise RecipeError(f"{path} is missing field(s): {', '.join(sorted(missing))}")

        recorded_hash = _check_sha256(payload["recipe_hash"], where=f"{path}: recipe_hash")
        if recorded_hash != expect_hash:
            raise RecipeError(
                f"{path} records recipe {recorded_hash} but sits under entry {expect_hash}"
            )
        _check_sha256(payload["dataset_version"], where=f"{path}: dataset_version")
        _check_sha256(payload["matrix_sha256"], where=f"{path}: matrix_sha256")
        _check_sha256(payload["row_times_sha256"], where=f"{path}: row_times_sha256")
        _check_text(payload["dataset_id"], where=f"{path}: dataset_id")

        rows = payload["rows"]
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
            raise RecipeError(f"{path}: rows must be a positive integer, got {rows!r}")
        columns = payload["columns"]
        if (
            not isinstance(columns, list)
            or not columns
            or not all(isinstance(column, str) and column for column in columns)
        ):
            raise RecipeError(f"{path}: columns must be a non-empty list of strings")
        nan_counts = payload["nan_counts"]
        if (
            not isinstance(nan_counts, list)
            or len(nan_counts) != len(columns)
            or not all(
                isinstance(count, int) and not isinstance(count, bool) and count >= 0
                for count in nan_counts
            )
        ):
            raise RecipeError(f"{path}: nan_counts must be one non-negative integer per column")
        version = payload["recipe_version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise RecipeError(f"{path}: recipe_version must be a positive integer, got {version!r}")
        return payload

    def _load_npy(self, path: Path, *, ndim: int) -> NDArray[Any]:
        """Load one stored array, checking its rank."""
        try:
            array = np.load(path, allow_pickle=False)
        except (OSError, ValueError) as exc:
            raise RecipeError(f"could not read {path}: {exc}") from exc
        if not isinstance(array, np.ndarray) or array.ndim != ndim:
            got = getattr(array, "ndim", type(array).__name__)
            raise RecipeError(f"{path} must hold a {ndim}-D array, got {got}")
        return array
