# Quant engine architecture

**Phase:** 0 — Foundation. **No quant code exists yet (Phase 5).** This
document fixes the contracts and quality bar so Phase 5 cannot quietly lower
them.

---

## 1. Responsibilities

The quant engine turns validated data into research-ready features and
statistics:

- rolling and windowed indicators (trend, volatility, momentum, volume);
- statistical properties (stationarity, autocorrelation, correlation
  structure, distribution fitting);
- transform utilities (normalisation, resampling, alignment, lagging);
- feature recipes that can be re-executed to reproduce a matrix exactly.

It does **not** decide anything. Signals, risk and execution belong to other
components.

---

## 2. Stack

| Library        | Use                                                          |
| -------------- | ------------------------------------------------------------ |
| NumPy          | Numerical kernels, deterministic array maths                 |
| Polars         | Fast columnar transforms on larger-than-memory frames        |
| Pandas         | Interop where the ecosystem requires it                      |
| SciPy          | Distributions, optimisation, signal processing               |
| scikit-learn   | Transformers with fit/transform semantics (careful with leakage) |
| statsmodels    | Formal statistical tests and time-series models              |

Dependencies are declared as the `quant` extra in `pyproject.toml` so a plain
foundation install stays small. Each addition must have a written reason.

---

## 3. Rules

1. **Determinism.** Same inputs ⇒ same outputs, across runs and machines.
   No wall-clock time, no unseeded randomness, no thread-order dependence in
   any calculation.
2. **No look-ahead.** Every windowed operation uses only data at or before
   the point being computed. Right-aligned by default; any centred or
   forward-looking window must be explicit, named and justified.
3. **No silent NaN policy.** Missing values are surfaced, not dropped
   silently. Every drop/fillna decision is recorded in the recipe.
4. **Timezone and calendar correctness.** Alignment is done on exchange
   sessions, not on naive integers.
5. **Type safety.** Full annotations; `mypy --strict` passes; no `Any`
   leaking into public signatures.
6. **Golden tests.** Every indicator and statistic has a hand-checked or
   independently computed expected value in `tests/quant/`.
7. **Versioned recipes.** A feature matrix records its recipe version and
   input dataset versions.

---

## 4. Leakage controls

| Risk                         | Control                                                     |
| ---------------------------- | ----------------------------------------------------------- |
| Scaling on the full sample   | Fit transforms inside the training window only              |
| Shifting the wrong direction | Explicit `lag`/`shift` semantics with direction assertions  |
| Future information in labels | Label construction helpers that assert `label_time >= info_time` |
| Duplicated rows across splits| Split utilities that assert disjoint indices                |

Property tests in `tests/quant/` will assert these mechanically rather than
by convention.

---

## 5. Layout (Phase 5)

```text
packages/quant/
├── src/harsh_quant_quant/     (or harsh_quant_os.quant)
│   ├── indicators/            rolling statistics
│   ├── stats/                 distributions, stationarity, correlation
│   ├── transforms/            normalisation, resampling, alignment
│   ├── recipes/               reproducible feature pipelines
│   └── registry/              versioned feature catalogue
└── tests/                     golden-value and property tests
```

---

## 6. Current state (Phase 0)

Nothing quant-specific is implemented. The only numeric helpers that exist
are in `@harsh-quant-os/shared` (`percentChange`, `safeDivide`, `roundTo`)
for display purposes, with unit tests. They are explicitly **not** the
quant engine.

---

## 7. Phase 5 exit criteria

- Indicator library with golden tests and documented formulas.
- Reproducible feature recipes with recorded versions.
- Leakage property tests passing.
- Benchmark data documented; performance measured, not assumed.
- `ruff`, `mypy --strict` and the full test suite green.
