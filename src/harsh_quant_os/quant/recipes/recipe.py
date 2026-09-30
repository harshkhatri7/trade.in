"""Versioned feature recipes: what to compute, from exactly which data.

quant-engine.md §3 rule 7 requires every feature matrix to record its
recipe version and its input dataset versions; rule 3 requires every
NaN decision to be written down. This module is that record:

- a :class:`DatasetRef` pins one dataset by name **and** by its
  content-addressed version (the SHA-256 the store computed when the
  bars were written), so a recipe cannot silently re-run on data that
  changed underneath it — :func:`~harsh_quant_os.quant.recipes.execute.execute`
  compares the pin against the batch and refuses on mismatch;
- a :class:`FeatureSpec` names one output column, the op that produces
  it, the source it reads, and every parameter the op takes;
- :class:`FeatureRecipe` binds those with ``recipe_version`` and a
  ``nan_policy`` sentence that is stored verbatim (rule 3: the decision
  is recorded, not implied).

**Canonical form and hash.** :meth:`FeatureRecipe.canonical_json`
serialises the payload with sorted keys and no redundant whitespace, so
two recipes that mean the same thing hash the same
(:meth:`recipe_hash` is SHA-256 over those bytes) and any edit to a
parameter, a version or the nan policy changes the identity. The stored
``recipe.json`` is exactly these bytes, and
:class:`~harsh_quant_os.quant.registry.store.FeatureStore` re-hashes on
load: a file edited after it was filed no longer hashes to its
directory and is refused.

Validation happens in two places on purpose: each
:class:`FeatureSpec`/:class:`DatasetRef` checks itself at construction
(local facts: names non-empty, ops known, params complete), while
:meth:`FeatureRecipe.validate` checks the facts that need the whole
recipe (unique names, sources resolvable to an input column or an
*earlier* feature, one pinned input). ``execute`` and ``save`` call
:meth:`validate` before doing anything, so no construction path —
including hand-built dataclasses — skips it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from harsh_quant_os.quant.recipes.ops import BAR_COLUMNS, OPS

__all__ = [
    "RECIPE_VERSION",
    "DatasetRef",
    "FeatureRecipe",
    "FeatureSpec",
    "RecipeError",
]

#: The only recipe schema this build writes and reads. Bump only with a
#: migration story; an unknown version is refused, never guessed at.
RECIPE_VERSION = 1

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_RECIPE_FIELDS = frozenset({"recipe_version", "inputs", "features", "nan_policy"})
_INPUT_FIELDS = frozenset({"dataset_id", "version"})
_FEATURE_FIELDS = frozenset({"name", "op", "source", "params"})


class RecipeError(Exception):
    """A recipe, a dataset pin, or a stored feature set is not valid.

    Raised for anything about *definition, provenance or integrity*:
    unknown ops, malformed JSON, version-pin mismatches, tampered or
    incomplete store entries. Invalid series data keeps raising
    ``InvalidSeries`` at the series boundary instead.
    """


@dataclass(frozen=True, slots=True)
class DatasetRef:
    """One input dataset, pinned by name and content-addressed version."""

    dataset_id: str
    version: str

    def __post_init__(self) -> None:
        if not self.dataset_id or not self.dataset_id.strip():
            raise RecipeError("dataset_id must not be empty")
        if not _SHA256_RE.fullmatch(self.version):
            raise RecipeError(
                f"dataset version must be a 64-character lowercase SHA-256, got {self.version!r}"
            )


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """One output column: its name, its op, its source, its parameters.

    Construction validates the local facts (this is the fast path for
    both hand-built and parsed recipes): the name is a clean non-empty
    string that does not shadow an input column, the op is in
    :data:`~harsh_quant_os.quant.recipes.ops.OPS`, and the parameters
    are exactly that op's parameters with integer values of at least 1.
    """

    name: str
    op: str
    source: str
    params: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip():
            raise RecipeError(
                f"feature name {self.name!r} must be non-empty and have no surrounding whitespace"
            )
        if self.name in BAR_COLUMNS:
            raise RecipeError(
                f"feature name {self.name!r} would shadow the input column of the same name"
            )
        if not self.source or self.source != self.source.strip():
            raise RecipeError(
                f"feature {self.name!r} must read from a non-empty source, got {self.source!r}"
            )
        # Copy so the recipe's canonical form cannot be changed through a
        # dict the caller kept a reference to.
        params = dict(self.params)
        object.__setattr__(self, "params", params)

        spec = OPS.get(self.op)
        if spec is None:
            known = ", ".join(sorted(OPS))
            raise RecipeError(
                f"feature {self.name!r} uses unknown op {self.op!r}; this build knows: {known}"
            )
        missing = [p for p in spec.params if p not in params]
        if missing:
            raise RecipeError(
                f"op {self.op!r} for feature {self.name!r} is missing parameter(s): "
                + ", ".join(missing)
            )
        unexpected = [p for p in params if p not in spec.params]
        if unexpected:
            raise RecipeError(
                f"op {self.op!r} for feature {self.name!r} has unexpected parameter(s): "
                + ", ".join(sorted(unexpected))
            )
        for key, value in params.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise RecipeError(
                    f"parameter {key!r} of feature {self.name!r} must be an integer >= 1, "
                    f"got {value!r}"
                )


@dataclass(frozen=True, slots=True)
class FeatureRecipe:
    """A versioned, hashable description of a feature pipeline.

    Attributes:
        recipe_version: :data:`RECIPE_VERSION` of the schema.
        inputs: Exactly one pinned :class:`DatasetRef` in this version.
        features: The output columns, in execution order — each source
            must be an input column or a feature defined earlier.
        nan_policy: Recorded verbatim in the stored recipe; this build's
            executor retains warm-up NaN and never drops or fills rows,
            so recipes say so in these words.
    """

    recipe_version: int
    inputs: tuple[DatasetRef, ...]
    features: tuple[FeatureSpec, ...]
    nan_policy: str

    def validate(self) -> None:
        """Check every rule that needs the whole recipe.

        Raises:
            RecipeError: The schema version is unknown; the input pin is
            not exactly one dataset; the nan policy is empty; there are
            no features; a feature name is duplicated or shadows an
            input column; or a feature reads a source that is neither an
            input column nor an earlier feature.
        """
        if self.recipe_version != RECIPE_VERSION:
            raise RecipeError(
                f"recipe_version {self.recipe_version} is not supported; this build "
                f"writes and reads version {RECIPE_VERSION}"
            )
        if len(self.inputs) != 1:
            raise RecipeError(
                f"a recipe pins exactly one input dataset in version {RECIPE_VERSION}, "
                f"got {len(self.inputs)}"
            )
        if not self.nan_policy or not self.nan_policy.strip():
            raise RecipeError(
                "nan_policy must record what happens to missing values "
                "(quant-engine.md section 3 rule 3)"
            )
        if not self.features:
            raise RecipeError("a recipe must declare at least one feature")

        known_sources = set(BAR_COLUMNS)
        seen: set[str] = set()
        for feature in self.features:
            if feature.name in seen:
                raise RecipeError(f"duplicate feature name {feature.name!r}")
            if feature.source not in known_sources:
                available = ", ".join(sorted(known_sources))
                raise RecipeError(
                    f"feature {feature.name!r} reads from {feature.source!r}, which is "
                    f"neither an input column nor an earlier feature; available: {available}"
                )
            seen.add(feature.name)
            known_sources.add(feature.name)

    def _payload(self) -> dict[str, Any]:
        """The JSON-shaped payload, built fresh for serialisation."""
        return {
            "recipe_version": self.recipe_version,
            "inputs": [
                {"dataset_id": ref.dataset_id, "version": ref.version} for ref in self.inputs
            ],
            "features": [
                {
                    "name": feature.name,
                    "op": feature.op,
                    "source": feature.source,
                    "params": dict(feature.params),
                }
                for feature in self.features
            ],
            "nan_policy": self.nan_policy,
        }

    def canonical_json(self) -> str:
        """The canonical serialisation: sorted keys, minimal whitespace.

        Two recipes with the same meaning produce byte-identical text
        regardless of construction order, which is what makes the hash a
        stable identity rather than a hash of dict ordering.
        """
        return json.dumps(self._payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def recipe_hash(self) -> str:
        """SHA-256 of :meth:`canonical_json` — the recipe's identity."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        """The exact bytes :class:`FeatureStore` writes as ``recipe.json``."""
        return self.canonical_json()

    @classmethod
    def from_json(cls, text: str) -> FeatureRecipe:
        """Parse and fully validate a recipe from JSON text.

        Field sets are checked strictly (unknown or missing fields are
        refused) so a typo in a hand-edited file surfaces instead of
        being dropped. Construction runs the local validations, and
        :meth:`validate` runs the whole-recipe ones.

        Raises:
            RecipeError: Not JSON, not an object, an unknown/missing
            field, a wrongly typed value, or any failed validation.
        """
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RecipeError(f"recipe is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise RecipeError(f"recipe must be a JSON object, got {type(payload).__name__}")
        _require_exact_fields(payload, _RECIPE_FIELDS, where="recipe")

        version = payload["recipe_version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise RecipeError(f"recipe_version must be an integer, got {version!r}")

        raw_inputs = payload["inputs"]
        if not isinstance(raw_inputs, list):
            raise RecipeError("inputs must be a JSON array")
        inputs: list[DatasetRef] = []
        for index, raw in enumerate(raw_inputs):
            where = f"inputs[{index}]"
            if not isinstance(raw, dict):
                raise RecipeError(f"{where} must be a JSON object")
            _require_exact_fields(raw, _INPUT_FIELDS, where=where)
            inputs.append(
                DatasetRef(
                    dataset_id=_text(raw["dataset_id"], f"{where}.dataset_id"),
                    version=_text(raw["version"], f"{where}.version"),
                )
            )

        raw_features = payload["features"]
        if not isinstance(raw_features, list):
            raise RecipeError("features must be a JSON array")
        features: list[FeatureSpec] = []
        for index, raw in enumerate(raw_features):
            where = f"features[{index}]"
            if not isinstance(raw, dict):
                raise RecipeError(f"{where} must be a JSON object")
            _require_exact_fields(raw, _FEATURE_FIELDS, where=where)
            params = raw["params"]
            if not isinstance(params, dict):
                raise RecipeError(f"{where}.params must be a JSON object")
            typed_params: dict[str, int] = {}
            for key, value in params.items():
                if not isinstance(key, str):
                    raise RecipeError(f"{where}.params has a non-string key {key!r}")
                if isinstance(value, bool) or not isinstance(value, int):
                    raise RecipeError(f"{where}.params[{key!r}] must be an integer, got {value!r}")
                typed_params[key] = value
            features.append(
                FeatureSpec(
                    name=_text(raw["name"], f"{where}.name"),
                    op=_text(raw["op"], f"{where}.op"),
                    source=_text(raw["source"], f"{where}.source"),
                    params=typed_params,
                )
            )

        recipe = cls(
            recipe_version=version,
            inputs=tuple(inputs),
            features=tuple(features),
            nan_policy=_text(payload["nan_policy"], "nan_policy"),
        )
        recipe.validate()
        return recipe


def _require_exact_fields(
    payload: dict[object, object], expected: frozenset[str], *, where: str
) -> None:
    """Refuse unknown or missing fields under ``where``."""
    actual = set(payload)
    unknown = actual - expected
    if unknown:
        raise RecipeError(f"{where} has unknown field(s): {', '.join(sorted(map(str, unknown)))}")
    missing = expected - actual
    if missing:
        raise RecipeError(f"{where} is missing field(s): {', '.join(sorted(missing))}")


def _text(value: object, where: str) -> str:
    """Return ``value`` as a non-empty string or raise."""
    if not isinstance(value, str):
        raise RecipeError(f"{where} must be a string, got {type(value).__name__}")
    return value
