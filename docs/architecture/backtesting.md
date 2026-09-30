# Backtesting architecture

**Phase:** 0 — Foundation. **No backtester exists yet (Phase 6).** The
requirements below are the contract Phase 6 must satisfy.

---

## 1. What a backtest is — and is not

A backtest is a **simulation of the past under stated assumptions**. It is
evidence about whether an idea survived a particular history. It is not a
forecast, not a guarantee, and not a substitute for out-of-sample and
paper-trading validation.

Every generated report must state: data version, period, timeframe, cost
model, slippage model, capital, and the limitations that apply.

---

## 2. Engine requirements

| Area                | Requirement                                                        |
| ------------------- | ------------------------------------------------------------------ |
| Data                | Only validated datasets, version pinned in the run manifest         |
| Timestamps          | Exchange sessions, timezone-aware, no naive arithmetic              |
| Order sequencing    | Events processed in strict time order; within a bar, a defined and documented ordering |
| Costs               | Explicit commission and fee model per venue/instrument              |
| Slippage            | Explicit model (fixed, spread-based, volume-participation) with parameters recorded |
| Position sizing     | Sizing rules are inputs, never hidden defaults                      |
| P&L                 | Realised/unrealised separated; exact numerics for money             |
| Drawdown            | Peak-to-trough on the equity curve, with time under water            |
| Exposure            | Gross/net exposure and turnover reported                            |
| Margin/borrow       | Modelled where the instrument requires it                            |
| Causality           | An order at time *t* can only use information available before *t*   |

---

## 3. Validation battery (Phase 7)

- **Out-of-sample testing** on data never used for selection.
- **Walk-forward testing** with rolling/expanding windows and a documented
  aggregation of results.
- **Parameter sensitivity**: performance surface, not a single optimum.
- **Regime analysis**: results split by volatility/trend regime.
- **Look-ahead detection**: automated checks that no feature or signal uses
  future information.
- **Leakage detection**: split-integrity and fit-scope assertions.
- **Survivorship-bias detection**: universe membership as-of the simulation
  date, not today.
- **Multiple-testing awareness**: the number of variants tried is recorded;
  headline metrics are adjusted rather than cherry-picked.

A strategy cannot be marked `validated` without out-of-sample and
walk-forward evidence attached. This is a product rule, not a guideline.

Implementation status: **out-of-sample testing**, **walk-forward
testing** and **parameter sensitivity** (rows 1-3) exist as of Phase 7
increments 1-3 — `validation.py` (chronological cut, append-only
access ledger, held-out evaluated once), `walkforward.py`
(rolling/expanding windows, per-window selection, the aggregation
defined in §9, and replay of every stored manifest) and
`sensitivity.py` (the declared grid, every cell, adjacency counts,
§9.4). Regime splits, multiple-testing adjustment and the
candidate/validated/rejected/archived workflow are **not
implemented yet**; the look-ahead, leakage and survivorship rows are
covered by the engine and Phase 5 checks described in §8.

---

## 4. Reproducibility

Every run writes a manifest containing:

```text
run_id, code_version (git sha), dataset versions, parameters,
cost/slippage model + inputs, universe definition, seed (if any),
start/end timestamps, engine version
```

Given a manifest, the run must be re-executable and must produce the same
numbers. Failing that reproducibility test is a defect, not a footnote.

---

## 5. Reporting rules

Reports must:

- distinguish in-sample from out-of-sample results;
- show the number of trades (small samples are called out);
- show drawdown and time under water alongside return;
- list assumptions and known biases;
- never use absolute language about future outcomes (enforced by
  `tests/unit/test_documentation.py`);
- carry a standard caveat that past performance is not indicative of future
  results.

---

## 6. Architecture

```text
datasets ──► backtest engine ──► simulated order book/fills
                    │                       │
                    ▼                       ▼
              run manifest           portfolio state ──► metrics
                    │                                       │
                    └────────────► report + artifacts ◄─────┘
```

The engine calls the **risk engine** for every simulated order through the
same trade-gate path used in paper trading, so a backtest cannot model
behaviour that live systems would refuse.

---

## 7. Current state (Phase 6)

Implemented in `src/harsh_quant_os/backtesting/` (the `packages/`
directory remains the Phase 0 requirements record):

| Concern                                                                       | Where                 |
| ----------------------------------------------------------------------------- | --------------------- |
| Bar sequencing, the intrabar rule, fills, ledger, the equity identity          | `engine.py`           |
| The strategy contract and the bounded history view                            | `strategy.py`         |
| Commission and slippage models as explicit inputs                             | `costs.py`            |
| Configured risk evaluation of every simulated order                           | `../safety/risk.py`   |
| Version-pinned dataset loading and the window-coverage check                  | `data.py`             |
| The run manifest and byte-identical re-execution                              | `manifest.py`         |
| The metric set with its assumptions                                           | `metrics.py`          |
| The report, cost sensitivity and the Wilson interval                          | `report.py`           |
| The reference strategy                                                        | `reference.py`        |
| Chronological splits, the held-out-once ledger, train-slice selection          | `validation.py`       |
| Walk-forward windows, per-window selection, the out-of-sample track, replay    | `walkforward.py`      |
| The declared parameter grid, every cell, adjacency counts, surface replay      | `sensitivity.py`      |
| `hqos backtest report`                                                        | `../cli.py`           |

Every simulated order is evaluated by `ConfiguredRiskEvaluator`
before it may fill — the same configured gate the paper-trading path
will use. Reports are written to `research/reports/`, which Git
ignores: a simulated result is an artefact of a run, never repository
content. Phase 7 increments 1–3 added the data-separation and
walk-forward layers, windowed replay (§9) and the parameter-sensitivity
surface (§9.4); regime splits, deflated metrics, benchmarks/nulls and
the promotion workflow are **not implemented**.

---

## 8. Phase 6 exit criteria

Assessed 2026-09-30. Each item is checked against tests that fail
when the claim stops being true:

- [x] **Deterministic engine with golden-value tests** —
  `tests/backtesting/test_engine.py` works the money path out by hand
  in `Decimal`; the suite reproduces it digit for digit.
- [x] **Costs, slippage and sizing are explicit inputs, recorded in
  the manifest** — `bps_commission` and `fixed_bps_slippage` are
  closed sets; an unknown model is refused, not guessed.
- [x] **Manifest-based reproducibility test passes** —
  `tests/backtesting/test_manifest.py` stores a manifest as JSON,
  re-executes it and compares three artefact hashes; a moved hash
  raises `ReproductionMismatch`.
- [x] **Look-ahead and leakage checks run automatically** — a
  `CausalityViolation` is asserted per fill, `HistoryView` raises
  `IndexError` past the current bar, and datasets load only by
  pinned, re-hashed version (Phase 5's split and fit-scope assertions
  cover the feature side).
- [x] **Reports include assumptions and limitations** — `report.py`
  states limitations first and separates assumptions from measured
  results; `tests/backtesting/test_report.py` asserts the ordering,
  the caveat and the absence of every `FORBIDDEN_CLAIMS` phrase.
- [x] **Risk evaluation is invoked in the simulated path** — every
  simulated order passes `ConfiguredRiskEvaluator` before it fills.

---

## 9. Phase 7 construction rules (data separation and walk-forward)

Increment 1 fixes these rules; the tests in
`tests/backtesting/test_validation.py` and
`tests/backtesting/test_walkforward.py` fail when any of them stops
being true.

### 9.1 The split (validation.py)

- The cut is **chronological**: the held-out suffix is the last N
  bars and starts strictly after every training bar. Never shuffled.
- `AccessLedger` is append-only (recording returns a new ledger) and
  refuses a **second** held-out touch — the test set consulted twice
  has become training data (anti-overfitting §2.2), so the second
  attempt raises instead of being logged.
- `evaluate_held_out` verifies the data handed in is the split's own
  pinned slice (same artefact, same span) before running; the run's
  manifest and §4 numbers come back together with the updated ledger.
- `select_on_train` runs every declared candidate with a fresh
  strategy instance and a fresh risk evaluator, scores them under an
  explicitly named objective, and records every variant, score and
  manifest. Ties resolve to the first declared candidate and are
  recorded in `tied` — a tie can never pass as a decisive win.

### 9.2 The walk-forward (walkforward.py)

- Windows are bar positions on the pinned dataset: `train` bars of
  selection followed immediately by `test` bars of evaluation,
  advancing `step` bars; `expanding=True` grows the training slice
  from bar 0 instead. The test slice starts exactly where its own
  training ends — a gap would hide data, an overlap would leak it.
- Each window is an **independent simulation**: fresh capital, fresh
  strategy, fresh risk evaluator; nothing carries between segments.
- Later windows' training slices contain earlier windows' test
  segments (they are past data by then). This is the standard
  walk-forward construction and is stated in every stored summary's
  notes: the track is **not** a single global hold-out — the
  held-out-once protocol above is that, and is separate.
- The out-of-sample track **compounds** each segment's net return as
  if the full capital were re-deployed at each segment start
  (`product(1 + r) - 1`, exact in `Decimal`); trade counts are pooled
  across segments; positive/negative/flat window counts, best and
  worst windows, and the variants-tried total
  (`candidates x windows`) sit beside the aggregate so the surface,
  not the optimum, is what a reader sees (anti-overfitting §2.4).
- The summary is stored as canonical JSON with every run's manifest
  embedded. Loading refuses: wrong `kind`, unknown version, edited
  notes, any manifest whose `run_id` no longer matches its payload,
  and any track that does not follow from the windows it summarises.
- Hit rate and Wilson interval appear only when round trips
  completed; otherwise they are `None`, never a plausible zero.

### 9.3 Replay and windowed manifests (increment 2)

- Every manifest records its own first and last bars as
  `dataset.start` / `dataset.end` (from its own equity curve, one
  mark per bar). `run_from_manifest` narrows the pinned dataset to
  exactly that span before re-running: a full-artefact run is the
  no-op it should be, a walk-forward window re-runs only its own
  bars. Both bounds must be exact bar timestamps of the pinned data
  — an unknown window, a backwards span or a naive timestamp is
  refused (`BacktestData.between`), never clamped or re-matched to
  nearby bars.
- A summary whose manifests record spans that disagree with its own
  window layout is refused at construction: evidence that
  contradicts the claim it is attached to cannot be reconciled by a
  reader, so the reader is never asked to.
- `replay_walk_forward` re-executes **every** manifest in a stored
  summary — each candidate's training run and each window's test
  run — and re-derives what can be derived: every selection score
  under the recorded objective, and every window's out-of-sample
  numbers from the reproduced run. It fails closed at the first
  mismatch: a missing builder, a different objective than the
  summary ranked under, a manifest that does not reproduce, a score
  that does not follow from its manifest, numbers that do not
  follow from theirs.
- The engine's floor applies to every segment: one bar to decide on
  and the next to fill on means each train and test slice needs at
  least two bars, so `walk_forward` refuses shorter layouts up
  front instead of failing deep inside a run.

### 9.4 The parameter-sensitivity surface (sensitivity.py, increment 3)

- The grid is **declared, not discovered**: axes are given up front
  (`parameter -> ordered distinct values`, read in the mapping's own
  order) and the surface is their cartesian product, last axis
  varying fastest. The cell count therefore *is* the
  multiple-testing denominator (anti-overfitting §2.4) — it cannot
  be quietly grown after seeing the data, and a surface whose cells
  do not match its declared grid is refused.
- Declared values are the **strings that reach the evidence**:
  `build` receives the exact declared strings, and the manifest
  records what `strategy.describe()` made of them. A builder that
  ignores an axis produces two identical manifests and is refused —
  a variation that never reaches the run is one cell counted twice.
- Every cell is a **full run**: fresh strategy, fresh risk
  evaluator, §3 manifest, exact-decimal numbers, the same slice of
  the same pinned dataset. The best cell is reported *beside* the
  surface (index plus `best_tied`), never instead of it.
- **Adjacency is structural**: neighbours differ in exactly one
  axis by one step (product-order strides, each pair counted once).
  Agreement is reported as two counts over those pairs — pairs and
  agreeing pairs — not as a score: a spike between two losers stays
  one cell, and the counts say so.
- The stored surface (canonical JSON) refuses: wrong kind/version,
  edited honesty notes, a manifest whose `run_id` no longer matches
  its payload, manifests pinning other data or other bounds, two
  cells sharing one manifest, and any stored statistic (best,
  ties, sign counts, score range, adjacency counts) that does not
  follow from the stored cells. `replay_sensitivity` goes further
  and re-executes every cell, re-deriving each score and each
  cell's numbers exactly.
