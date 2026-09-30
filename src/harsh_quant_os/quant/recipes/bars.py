"""Loading stored bars: one verification boundary, two representations.

The bridge from the data store (exact ``Decimal`` CSV, content-addressed
directories) to what each consumer needs:

- :func:`load_stored_bars` is the shared verification step — name
  safety, version resolution, and the rest of this list; it keeps exact
  ``Decimal`` bars and is what the backtest engine reads.
- :func:`load_bar_batch` converts the same verified bars to float64
  arrays for indicator arithmetic; the stored CSV stays exact on disk.

Verification rules, applied to both:

- **The version is recomputed, not trusted.** ``data/clean/<name>/`` is
  keyed by the SHA-256 of the clean artefact bytes; the loader hashes
  the file again and refuses if the file does not match its directory —
  a renamed or replaced artefact cannot masquerade as the version a
  recipe pinned.
- **Missing volume is refused, not filled.** ``Bar.volume`` may be
  ``None`` (the provider reported none); this build never invents one,
  so a dataset with holes in its volume column is refused with a count
  (quant-engine.md §3 rule 3).
- **Nothing is resampled or reordered.** Bars load in stored order and
  :class:`BarBatch` requires strictly increasing times, so every
  downstream right-aligned window lines up with real chronology.

:class:`BarBatch` validates at construction like every other quant
boundary: an invalid batch raises :class:`InvalidSeries` before a
recipe ever sees it.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from harsh_quant_os.data.providers import Bar
from harsh_quant_os.data.store import read_bars
from harsh_quant_os.quant.recipes.recipe import RecipeError
from harsh_quant_os.quant.series import InvalidSeries

__all__ = ["BarBatch", "load_bar_batch", "load_stored_bars"]


@dataclass(frozen=True, slots=True)
class BarBatch:
    """One dataset's bars as arrays, pinned by name and version.

    The six columns are taken as given (coerced to ``int64``/``float64``,
    not copied) and must all be one-dimensional, equally long, at least
    one row, finite, and — for ``time`` — strictly increasing.

    Attributes:
        name: Dataset name, e.g. ``kraken.xbtusd.1m``.
        version: 64-character SHA-256 of the clean artefact.
        time: Open times, unix seconds.
        open: Open prices.
        high: High prices.
        low: Low prices.
        close: Close prices.
        volume: Volume bars.
    """

    name: str
    version: str
    time: NDArray[np.int64]
    open: NDArray[np.float64]
    high: NDArray[np.float64]
    low: NDArray[np.float64]
    close: NDArray[np.float64]
    volume: NDArray[np.float64]

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise InvalidSeries("batch name must not be empty")
        if not re.fullmatch(r"[0-9a-f]{64}", self.version):
            raise InvalidSeries(
                f"batch version must be a 64-character lowercase SHA-256, got {self.version!r}"
            )

        time = np.asarray(self.time, dtype=np.int64)
        columns: dict[str, NDArray[np.float64]] = {
            "open": np.asarray(self.open, dtype=np.float64),
            "high": np.asarray(self.high, dtype=np.float64),
            "low": np.asarray(self.low, dtype=np.float64),
            "close": np.asarray(self.close, dtype=np.float64),
            "volume": np.asarray(self.volume, dtype=np.float64),
        }

        sizes = {"time": time.size, **{label: column.size for label, column in columns.items()}}
        if len(set(sizes.values())) != 1:
            lengths = ", ".join(f"{label}={size}" for label, size in sizes.items())
            raise InvalidSeries(f"bar columns must all have the same length, got {lengths}")
        if time.size == 0:
            raise InvalidSeries("a batch carries at least one bar, got 0")
        if time.size > 1:
            steps = np.diff(time)
            if not bool(np.all(steps > 0)):
                first = int(np.flatnonzero(steps <= 0)[0]) + 1
                raise InvalidSeries(
                    f"bar times must strictly increase; row {first} does not follow row "
                    f"{first - 1} (duplicated or out-of-order bars are refused, not merged)"
                )

        for label, column in columns.items():
            if not bool(np.all(np.isfinite(column))):
                row = int(np.flatnonzero(~np.isfinite(column))[0])
                raise InvalidSeries(f"{label} column has a non-finite value at row {row}")
        volume = columns["volume"]
        if bool(np.any(volume < 0.0)):
            row = int(np.flatnonzero(volume < 0.0)[0])
            raise InvalidSeries(f"volume column has a negative value at row {row}")

        object.__setattr__(self, "time", time)
        for label, column in columns.items():
            object.__setattr__(self, label, column)

    def column(self, name: str) -> NDArray[np.float64]:
        """Return the named input column (``open``/``high``/``low``/``close``/``volume``).

        Raises:
            InvalidSeries: The name is not a batch column.
        """
        columns = {
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }
        if name not in columns:
            raise InvalidSeries(f"{name!r} is not a batch column; available: " + ", ".join(columns))
        return columns[name]


def load_stored_bars(root: Path, name: str, *, version: str | None = None) -> tuple[str, list[Bar]]:
    """Resolve, verify and read one stored clean artefact as bars.

    The single verification boundary for the content-addressed store,
    shared by :func:`load_bar_batch` (which converts to float64) and
    the backtest engine's data loader (which keeps exact ``Decimal``
    prices). Same refusal list for every caller:

    Args:
        root: The data root (the directory holding ``clean/``).
        name: Dataset name — a plain directory name; path separators and
            ``..`` are refused so a name cannot escape the store.
        version: Which stored version to load. ``None`` requires the
            dataset to have exactly one version and takes it; more than
            one is an error rather than a guess about which is current.

    Returns:
        ``(version, bars)`` — the content-addressed version, recomputed
        from the artefact bytes and checked against the directory the
        store hashed them into, and the bars in stored order.

    Raises:
        RecipeError: The name is not a plain directory name; no such
        dataset/version exists; the artefact's hash does not match its
        directory; the dataset holds no bars; or any bar lacks volume
        (counted in the message — never filled in silently).
    """
    if not name or Path(name).name != name or name in {".", ".."}:
        raise RecipeError(f"dataset name must be a plain directory name, got {name!r}")
    dataset_dir = root / "clean" / name
    if not dataset_dir.is_dir():
        raise RecipeError(f"no stored dataset named {name!r} under {dataset_dir}")

    available = sorted(entry.name for entry in dataset_dir.iterdir() if entry.is_dir())
    if version is None:
        if not available:
            raise RecipeError(f"dataset {name!r} has no stored versions under {dataset_dir}")
        if len(available) > 1:
            raise RecipeError(
                f"dataset {name!r} has {len(available)} stored versions; pass version= to "
                f"choose one of: {', '.join(available)}"
            )
        version = available[0]
    elif version not in available:
        stored = ", ".join(available) if available else "(none)"
        raise RecipeError(f"dataset {name!r} has no version {version}; stored: {stored}")

    bars_path = dataset_dir / version / "bars.csv"
    if not bars_path.is_file():
        raise RecipeError(f"version {version} of {name!r} has no bars.csv at {bars_path}")

    payload = bars_path.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != version:
        raise RecipeError(
            f"{bars_path} does not match its recorded version: the file hashes to {actual}, "
            f"the directory says {version}"
        )

    bars = read_bars(bars_path)
    if not bars:
        raise RecipeError(f"dataset {name!r} version {version} contains no bars")

    volumes = [bar.volume for bar in bars if bar.volume is not None]
    if len(volumes) != len(bars):
        absent = len(bars) - len(volumes)
        raise RecipeError(
            f"{absent} of {len(bars)} bars in {name!r} have no volume; a stored dataset "
            "carries a real volume column and this build never invents one "
            "(quant-engine.md section 3)"
        )

    return version, bars


def load_bar_batch(root: Path, name: str, *, version: str | None = None) -> BarBatch:
    """Load a stored clean dataset under ``root`` as a :class:`BarBatch`.

    Resolves and verifies the artefact through
    :func:`load_stored_bars` (same refusals, documented there), then
    converts the exact stored values to ``int64``/``float64`` arrays for
    indicator arithmetic — the stored CSV stays exact on disk.

    Returns:
        The batch, pinned to the recomputed content-addressed version.

    Raises:
        RecipeError: Anything :func:`load_stored_bars` refuses, or a bar
        lacks volume at this layer's own check (both refuse; neither
        fills).
    """
    version, bars = load_stored_bars(root, name, version=version)

    volumes = [float(bar.volume) for bar in bars if bar.volume is not None]
    if len(volumes) != len(bars):
        absent = len(bars) - len(volumes)
        raise RecipeError(
            f"{absent} of {len(bars)} bars in {name!r} have no volume; a BarBatch carries a "
            "real volume column and this build never invents one (quant-engine.md section 3)"
        )

    return BarBatch(
        name=name,
        version=version,
        time=np.array([int(bar.timestamp.timestamp()) for bar in bars], dtype=np.int64),
        open=np.array([float(bar.open) for bar in bars], dtype=np.float64),
        high=np.array([float(bar.high) for bar in bars], dtype=np.float64),
        low=np.array([float(bar.low) for bar in bars], dtype=np.float64),
        close=np.array([float(bar.close) for bar in bars], dtype=np.float64),
        volume=np.array(volumes, dtype=np.float64),
    )
