"""Reproducible feature pipelines: pinned inputs, ordered ops, one hash.

A :class:`FeatureRecipe` states which dataset (by content-addressed
version) feeds which features (from a closed op whitelist, in an order
that cannot express look-ahead), and
:meth:`~harsh_quant_os.quant.recipes.execute.execute` turns it into a
:class:`~harsh_quant_os.quant.recipes.execute.FeatureMatrix` that
carries that provenance with it. :func:`load_bar_batch` is the bridge
from the on-disk store to the executor's input.

The pieces:

- :mod:`~harsh_quant_os.quant.recipes.recipe` — recipe schema,
  canonical JSON, SHA-256 identity, validation;
- :mod:`~harsh_quant_os.quant.recipes.ops` — the closed op whitelist;
- :mod:`~harsh_quant_os.quant.recipes.bars` — :class:`BarBatch` and its
  loader from ``data/clean``;
- :mod:`~harsh_quant_os.quant.recipes.execute` — execution and the
  matrix that results.

Saving, listing and verifying executed recipes is the registry's job
(:mod:`harsh_quant_os.quant.registry`), not this package's.
"""

from __future__ import annotations

from harsh_quant_os.quant.recipes.bars import BarBatch, load_bar_batch
from harsh_quant_os.quant.recipes.execute import FeatureMatrix, execute
from harsh_quant_os.quant.recipes.ops import BAR_COLUMNS, OPS, OpSpec
from harsh_quant_os.quant.recipes.recipe import (
    RECIPE_VERSION,
    DatasetRef,
    FeatureRecipe,
    FeatureSpec,
    RecipeError,
)

__all__ = [
    "BAR_COLUMNS",
    "OPS",
    "RECIPE_VERSION",
    "BarBatch",
    "DatasetRef",
    "FeatureMatrix",
    "FeatureRecipe",
    "FeatureSpec",
    "OpSpec",
    "RecipeError",
    "execute",
    "load_bar_batch",
]
