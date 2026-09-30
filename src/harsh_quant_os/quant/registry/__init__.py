"""The versioned feature catalogue (quant-engine.md §5 ``registry/``).

:class:`FeatureStore` files executed recipes by their hash, records the
dataset versions they were computed from, and refuses to treat an
interrupted save, an edited recipe or a modified matrix as complete —
see :mod:`harsh_quant_os.quant.registry.store` for the file layout and
the two rules (``meta.json`` written last; re-saving is a determinism
check, not an overwrite).

Typical use::

    store = FeatureStore(Path("data/features"))
    digest = store.save(recipe, execute(recipe, bars))
    store.verify(digest)              # silent = consistent
    same = store.load_matrix(digest)  # checksums verified on read
"""

from __future__ import annotations

from harsh_quant_os.quant.registry.store import (
    FeatureStore,
    canonical_matrix_sha256,
    canonical_times_sha256,
)

__all__ = [
    "FeatureStore",
    "canonical_matrix_sha256",
    "canonical_times_sha256",
]
