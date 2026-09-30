# Quant engine architecture

**Phase:** 5 — Quant engine, in progress. This document fixes the contracts
and quality bar for the code Phase 5 adds, so they cannot be quietly lowered.

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

## 6. Current state (Phase 5, increment 3)

Implemented:

- `src/harsh_quant_os/quant/` — the engine package (`harsh_quant_os.quant`):
  - `series.py` — the shared input boundary: an empty, non-1-D or
    non-finite series, and an invalid or over-long window, raise
    `InvalidSeries` before any window rolls. Warm-up NaN in outputs is
    per-function and documented, distinct from missing input data.
  - `indicators/` — `sma`, `ema` (first-value seed, no hidden warm-up
    cut), `rolling_std` (`ddof=0`), `rolling_zscore` (flat window → NaN,
    never an invented 0), `bollinger_bands`, `rolling_vwap`
    (zero-volume window → NaN, negative volume refuses), `rsi` (Wilder's
    smoothing, with the flat → 50 / no-loss → 100 / no-gain → 0 policies
    stated in the module), `macd` (fast < slow enforced). Every formula
    is written out in the module docstrings.
  - `stats/` — `adf_stationarity` (augmented Dickey-Fuller: statistic,
    p-value, sample sizes and critical values in one typed result; the
    p-value comes from statsmodels' MacKinnon approximation, with
    `result_object=False` pinned so a future default change cannot move
    this contract; the `stationary` flag is exactly `p < alpha`), `acf`
    (biased `1/n` estimator, `acf[0] = 1`, lags capped below the series
    length, a constant series refuses instead of returning `NaN`), and
    `correlation_matrix` (Pearson over equally long columns; a constant
    column and unequal lengths refuse with the column named; one column
    returns `[[1.0]]`).
  - `transforms/` — the leakage-controlled research transforms:
    - `returns.py` — `simple_returns`, `log_returns` (strictly positive
      prices enforced; zero denominators refuse) kept aligned with the
      input, and `forward_return`, a **label** whose last `horizon`
      positions are NaN because those outcomes are not yet observable;
    - `lag.py` — one-directional shifting: `out[i] = values[i-periods]`,
      negative shifts refused by name (they would read the future),
      zero refused (a no-op must not stand in for a real shift);
    - `scaling.py` — `StandardScaler`, a frozen fit/transform whose
      `fit` sees only the values passed and records `n`, so the sample
      it was fitted on stays explicit;
    - `splits.py` — `chronological_split` (time-ordered only, cut point
      validated to leave both sides non-empty, disjointness re-asserted
      before returning) and the public `assert_disjoint` for
      caller-built index sets.
- `tests/quant/` — 132 tests total:
  - `test_indicators.py` (46): golden values hand-derived in the test
    file (EMA as exact fractions `5/3, 23/9, 95/27, 365/81`; RSI's
    Wilder recursion worked through fraction by fraction; population
    variances and VWAP arithmetic), an independent window-loop
    cross-check, and for every function the three mechanical properties
    quant-engine.md requires: appending a future bar changes no earlier
    output (no look-ahead), two calls are bit-identical (determinism),
    and the input array is never mutated — plus the validation refusals.
  - `test_stats.py` (40): the ADF statistic is cross-checked against an
    OLS t-statistic computed from scratch in the test (design matrix,
    least squares, standard error — no statsmodels); the behavioural
    fixtures are a written-out Park-Miller LCG (raw noise: null
    rejected; its cumulative sum — a genuine random walk: not rejected)
    with threshold assertions rather than pinned library output; `acf`
    and the correlation matrix are compared against hand-worked values.
  - `test_transforms.py` (46): the §4 leakage controls are asserted
    mechanically — `lag` refuses a negative shift by name and matches
    the hand-derived direction on golden values; the scaler's
    statistics come from exactly its fit sample (and a full-sample fit
    would differ), transforming future data cannot re-centre it, and the
    fitted object is frozen; splits are checked with NumPy directly for
    disjointness, completeness and time order (not via the helper under
    test); a forward label's unobservable tail is NaN and appending data
    never revises a label that was already computable; plus returns
    golden values and the validation refusals.
- The `quant` extra (NumPy, Pandas, Polars, SciPy, scikit-learn,
  statsmodels) installed in `.venv` per §2.

Not started yet, all still Phase 5: `recipes/`, `registry/`,
resampling/session-alignment helpers, and the measured benchmark.
The only other numeric helpers remain `@harsh-quant-os/shared`
(`percentChange`, `safeDivide`, `roundTo`) for display purposes, with unit
tests — explicitly **not** the quant engine.

---

## 7. Phase 5 exit criteria

- Indicator library with golden tests and documented formulas.
- Reproducible feature recipes with recorded versions.
- Leakage property tests passing.
- Benchmark data documented; performance measured, not assumed.
- `ruff`, `mypy --strict` and the full test suite green.
