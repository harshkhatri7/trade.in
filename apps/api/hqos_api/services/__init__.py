"""Application services: payload builders and read-side loaders.

The builders are pure functions — a model in, a contract out, nothing
decided. The dataset loaders additionally read the manifest and the
stored artefacts, because "what is in this dataset" is a question about
the world rather than about a payload; they still never decide anything,
and they know nothing about HTTP.
"""

from __future__ import annotations

from hqos_api.services.datasets import (
    DEFAULT_BARS_LIMIT,
    MAX_BARS_LIMIT,
    DatasetNotFound,
    DatasetNotStored,
    DatasetReadError,
    build_bar_point,
    build_provenance_entry,
    build_summary,
    load_bars,
    load_dataset_detail,
    load_datasets,
)
from hqos_api.services.system import build_health, build_ready, service_name

__all__ = [
    "DEFAULT_BARS_LIMIT",
    "MAX_BARS_LIMIT",
    "DatasetNotFound",
    "DatasetNotStored",
    "DatasetReadError",
    "build_bar_point",
    "build_health",
    "build_provenance_entry",
    "build_ready",
    "build_summary",
    "load_bars",
    "load_dataset_detail",
    "load_datasets",
    "service_name",
]
