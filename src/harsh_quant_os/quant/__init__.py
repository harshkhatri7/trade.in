"""HARSH QUANT OS quant engine (Phase 5).

Turns validated data into research-ready features and statistics. It does
**not** decide anything: signals, risk and execution belong elsewhere
(``docs/architecture/quant-engine.md`` §1).

Layout:

- ``quant.indicators`` — rolling and windowed indicators (trend,
  volatility, momentum, volume);
- ``quant.stats`` — formal statistical tests and correlation structure;
- ``quant.transforms`` — normalisation, lagging, alignment;
- ``quant.recipes`` — reproducible feature pipelines with recorded input
  dataset versions;
- ``quant.registry`` — the versioned feature catalogue.

Every module obeys the rules in ``docs/architecture/quant-engine.md`` §3:
deterministic, right-aligned (no look-ahead), missing values surfaced,
``mypy --strict`` clean, and every calculation golden-tested in
``tests/quant/``.
"""
