# packages/quant — Quantitative engine (Phase 5)

Indicators, statistics, transforms and reproducible feature recipes.

**Status: not implemented.** Numeric dependencies are declared as the `quant`
extra in `pyproject.toml` and are intentionally not installed yet:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[quant]"
```

Planned shape:

```text
packages/quant/
├── indicators/    rolling and windowed statistics
├── stats/         distributions, stationarity, correlation
├── transforms/    normalisation, resampling, alignment
├── recipes/       reproducible feature pipelines
└── registry/      versioned feature catalogue
```

Quality bar: deterministic, no look-ahead, no silent NaN policy, golden tests
for every calculation, full `mypy --strict`.

See [docs/architecture/quant-engine.md](../../docs/architecture/quant-engine.md).
