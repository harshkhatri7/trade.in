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

## 6. Current state (Phase 5, increment 4)

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
  - `recipes/` — reproducible feature pipelines:
    - `recipe.py` — `DatasetRef` (dataset name plus the
      content-addressed SHA-256 the store computed), `FeatureSpec`
      (output name, op, source, parameters — validated at construction
      against the closed op list) and `FeatureRecipe` (schema version,
      exactly one pinned input, features in execution order, a
      `nan_policy` sentence recorded verbatim for rule 3). Canonical
      JSON is sorted-key with no redundant whitespace, so the recipe's
      SHA-256 identity does not depend on construction order;
      `from_json` refuses unknown and missing fields;
    - `ops.py` — the closed whitelist (`sma`, `ema`, `rolling_std`,
      `rolling_zscore`, `rsi`, `log_returns`, `simple_returns`,
      `lag`), each mapping to its golden-tested primitive; an op name
      from a file never reaches `eval` or a dynamic import, and an
      unknown one fails validation with the known names listed;
    - `bars.py` — `BarBatch` (equal lengths, strictly increasing times,
      finite columns, non-negative volume, validated at construction)
      and `load_bar_batch`, which re-hashes the clean artefact and
      refuses it if the file no longer matches its content-addressed
      directory, requires an explicit version when several exist, and
      refuses missing volume with a count instead of filling it;
    - `execute.py` — three refusal-ordered steps: validate the recipe;
      compare the dataset name and version pin against the batch (both
      sides named in the error, so a recipe never silently runs on
      other data); run features in declaration order where a source is
      an input column or an *earlier* feature — forward references are
      unrepresentable, and a chained source carrying warm-up NaN is
      refused by feature name rather than computed through;
  - `registry/` — `FeatureStore`, the §5 catalogue: entries keyed by
    recipe hash holding `recipe.json`, `values.npy`, `times.npy` and
    `meta.json` (dataset identity, shape, per-column NaN counts, and
    SHA-256 over canonical little-endian bytes of both artefacts).
    `meta.json` is written last and its presence is the completion
    marker — an interrupted save is refused by name and repaired by a
    re-save; re-saving a complete entry compares checksums and raises
    on a determinism violation instead of overwriting; `verify`
    cross-checks the record against the recipe (dataset pin, column
    order, NaN counts); `load_recipe` re-hashes the file, so a recipe
    edited after filing no longer hashes to its directory and is
    refused.
- `scripts/quant/benchmark_features.py` — measures execution on a real
  stored dataset through the same `load_bar_batch` path research code
  uses, and checks every timed run against the cold run by SHA-256 over
  canonical bytes (exit 1 if any run differed). Measured on this
  machine (Python 3.12.10, numpy 2.5.3, Windows 11): dataset
  `kraken.xbtusd.1m` version `0a7dd69ff1c410758ac2d49083edae304c8de80be8badfaaeeb7996c270e29b0`,
  661 rows × 9 features (126 NaN cells), cold run 2.766 ms, 50 timed
  runs min/median/max 1.235/1.847/4.528 ms, **50/50 runs
  SHA-256-identical** to the cold run (recipe hash
  `b38da597c4543091ea49158d69e5fd51b874213a87f35aa3520d2919bc6ee48e`,
  matrix hash
  `0a6138722513abd4492b56508cb11a847d06df2c4410261ce8a7415eea5c1a45`).
  The milliseconds are observations that vary between runs — rerun the
  script to measure again; the reproduction count is what the harness
  asserts, not what it assumes.
- `tests/quant/` — 195 tests total:
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
  - `test_recipes.py` (47): the canonical JSON is compared against a
    string written out in the test byte for byte with its SHA-256
    recomputed independently over those bytes; every meaningful change
    changes the hash; execution is bit-identical across runs and leaves
    the batch untouched; the version pin refuses a different dataset
    version or name with both sides in the message; primitives' own
    refusals travel up through the recipe unchanged; the loader's
    artefact-hash check, missing-volume refusal, multi-version
    refusal and path-escape refusal run against a store fixture the
    test writes itself, so the suite never depends on `data/` existing;
  - `test_registry.py` (16): round trip of every stored field;
    reproduce-twice **through disk** (execute → save → execute → load,
    all three bit-identical); identical record bytes across two store
    roots; refusals for a wrong-recipe matrix, a determinism violation
    (original entry shown untouched), a tampered `recipe.json`,
    `values.npy` and `meta.json`, an incomplete entry (not listed,
    load refused, re-save repairs), and malformed hashes; `verify`
    catching what one file cannot contradict about itself (dataset
    pin, column order, NaN counts); loaded arrays isolated from the
    store in both directions.
- The `quant` extra (NumPy, Pandas, Polars, SciPy, scikit-learn,
  statsmodels) installed in `.venv` per §2.

Not started yet, all still Phase 5: resampling/session-alignment
helpers, §4's timestamped `label_time >= info_time` label assertion,
and distribution fitting — named in §1's responsibility list but not an
exit criterion in §7, so recorded as a gap rather than quietly dropped.
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
