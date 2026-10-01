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
testing**, **parameter sensitivity** and **regime analysis** (rows
1-4) exist as of Phase 7 increments 1-4 — `validation.py`
(chronological cut, append-only access ledger, held-out evaluated
once), `walkforward.py` (rolling/expanding windows, per-window
selection, the aggregation defined in §9, and replay of every stored
manifest), `sensitivity.py` (the declared grid, every cell,
adjacency counts, §9.4) and `regimes.py` (causal labels with
declared thresholds, entry-time attribution, §9.5).
**Multiple-testing adjustment** exists as of Phase 7 increment 6:
`deflated.py` prices a recorded shot count into the headline (§9.7),
and the report renders the count when one is supplied and says
"not recorded" when none is — a count is never invented. The
candidate/validated/rejected/archived workflow exists as of Phase 7
increment 7: `promotion.py` enforces the sentence above itself — a
record cannot move to, load at, or be hand-written into `validated`
without held-out, walk-forward, sensitivity and critique evidence
recorded, the critique from someone other than the candidate's
author, and a stated reason on every rejection (§9.8). The
look-ahead, leakage and survivorship rows are covered by the engine
and Phase 5 checks described in §8.

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
| Causal regime labels, entry-time attribution, the split and its honesty flags | `regimes.py`          |
| The same-universe passive reference: first fill, fixed-point sizing, identities | `benchmark.py`        |
| The seeded shuffled-signal null: capture, permutation, counts reported as counts | `null.py`             |
| The deflated Sharpe: a recorded shot count priced into the headline, self-accounting | `deflated.py` |
| Promotion stages, evidence gates, append-only history, tamper-checked file moves      | `promotion.py`        |
| `hqos backtest report`                                                        | `../cli.py`           |
| `hqos strategy register/evidence/promote/reject/archive/show`                 | `../cli.py`           |

Every simulated order is evaluated by `ConfiguredRiskEvaluator`
before it may fill — the same configured gate the paper-trading path
will use. Reports are written to `research/reports/`, which Git
ignores: a simulated result is an artefact of a run, never repository
content. Phase 7 increments 1–7 added the data-separation and
walk-forward layers, windowed replay (§9), the parameter-sensitivity
surface (§9.4), the causal regime split (§9.5), the benchmark and
shuffled-signal null (§9.6), the §2.5 deflated headline (§9.7) and
the §3 promotion workflow (§9.8).

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

### 9.5 Regime segmentation (regimes.py, increment 4)

- **Labels are causal**: a bar's label is a function of that bar and
  the trailing `window` bars behind it — never of the bars ahead.
  Thresholds are *declared* inputs; a quantile of the whole sample
  would read the future, so the built-ins take their thresholds as
  arguments instead.
- **Warm bars are `undefined`, their own segment**: until a full
  trailing window exists there is no label to give, and those bars
  are counted rather than folded into whatever regime follows them.
- **The rule travels with the labels**: `RegimeLabels` carries the
  human-readable rule beside the per-bar labels and `RegimeSplit`
  keeps it — a split reported without the rule that produced it
  would be a metric without its assumptions.
- **Attribution is by entry**: a completed cycle belongs to the
  regime in force when the position was *opened* — the decision
  point. A trade can span regimes and its P&L is not split to
  pretend otherwise; the position still open at the end is counted
  under its entry regime and sits in no cycle's P&L (an unclosed
  trade is neither win nor loss, exactly as §4 rules).
- **The split is retrospective reporting, not selection**: one walk
  of the run's own ledger (`trade_records`, the same reconstruction
  `compute_metrics` reads), grouped by label. Labels covering a
  different bar count, a cycle whose entry is not one of the run's
  own bar times, a flat-ending run whose realised total the walk
  cannot reproduce, and segments or splits that cannot account for
  themselves are all refused.
- A profitable split whose gains all entered under one regime
  reports `regime_specific`: reported as regime-specific, not as
  general (anti-overfitting §2.7).
- The two built-ins — `volatility_regimes` (trailing population
  stdev of close-to-close returns, the quant package's ddof=0
  convention) and `trend_regimes` (trailing return against declared
  up/down magnitudes) — are exact `Decimal`; any other causal labels
  (liquidity included) may be supplied through `RegimeLabels`.

### 9.6 Benchmarks and nulls (benchmark.py, null.py, increment 5)

- **The passive benchmark is a fixed rule, not a strategy**: it
  decides nothing (no look-ahead to guard, no risk gate to pass),
  fills on the window's second bar's open — the first price any
  strategy can act on — with the run's own slippage applied by the
  model's own method, sizes the capital by a fixed point of
  `notional + commission(notional) = capital` (refused outright if
  the model would eat the capital or never settle) so the cash
  residue can never go negative, and marks to the final close with
  no exit fee: the same marking the engine gives an open position,
  so neither side of the comparison pays an exit the other does not.
  Long only — a short reference would need borrow costs this engine
  does not model, and none is invented. Its dataclass re-derives the
  spend identity, the ending identity and the net return from its
  own fields on construction, and carries the assumptions beside the
  numbers (§5's rule).
- **The null re-times the signals, nothing else**: one capture run
  records the declared strategy's decision per bar (strategies are
  pure by contract — two runs decide identically), and each trial
  permutes that exact tuple across the bars and runs it through the
  engine as an exogenous-signal strategy with a fresh evaluator,
  same data, same config, same costs. The seed is explicit and
  required — there is no default — and carried in the report,
  because randomness that was not recorded cannot be audited; the
  permutation is drawn from the seeded generator's stable
  `random()` values under a stable sort, so
  `(seed, trials, bar count)` replays it exactly.
- **The report counts, it does not conclude**: every trial's score
  is kept in trial order (no "best trial" view), and
  `extreme_fraction` is the count of trials whose score matched or
  beat the actual (ties counted) over the trials — a plain count,
  never a p-value and never the probability that the strategy has
  no edge. A value near 1 is consistent with the timing carrying
  nothing, which is what anti-overfitting §2.6 asks the reader to
  consider.

### 9.7 The deflated headline (deflated.py, increment 6)

- **The count is an input, never a default**: `deflated_sharpe`
  takes the shot count explicitly — how many variants were tried,
  `len(trace.runs)` from a `SelectionTrace` or the honest record of
  every attempt (anti-overfitting §2.5) — because a default count
  would be a guess wearing a number's clothes. Zero, a non-int and a
  `bool` are refused.
- **The model, stated so it can be checked**: per-period returns —
  the same per-bar equity returns `VolatilityStats` uses, in
  per-period units (the report's annualised Sharpe is this figure
  times `sqrt(bar frequency)`), population moments (ddof=0, the
  quant package's convention) — with
  `V[SR] = (1 − skew·SR + (kurt − 1)/4·SR²)/(T − 1)` where `kurt`
  is Pearson (3 for a normal); `SR0 = sqrt(V[SR])` times Blom's
  expected maximum of `trials` standard normals (exactly 0 for one
  shot, the max of one draw having mean 0); and
  `Φ((SR − SR0)/sqrt(V[SR]))` through the stdlib
  `statistics.NormalDist` — no new dependency. Statistics run in
  `float` like the quant package; returns are `Decimal` on the way
  in, and money never leaves `Decimal` anywhere else.
- **A headline that cannot account for itself is refused**: the
  dataclass re-derives SR0 and the deflated value from its own
  stored fields and raises if either differs, on top of the floors
  (at least one recorded shot, at least two periods, a positive
  estimator variance, finite figures, the deflated value within
  [0, 1], a non-empty note). A flat series is refused too: with no
  dispersion the Sharpe is not a number, and infinity is not
  reported in its place.
- **The report renders what was computed and nothing else**: with a
  `deflated` argument the Uncertainty line records the count, a
  "Multiple-testing adjustment" section carries every figure beside
  the honesty note — the deflated value is the normal-model
  probability that the best of the recorded shots under a no-skill
  null would fall short of this Sharpe, **not the probability that
  the strategy works** — and the standing limitation states the
  model's assumptions (iid normal shots, a complete count). Without
  one, the report says "Variants tried: not recorded for this run",
  exactly as before: a count is never invented to fill the section.
- Golden traces hand-computed: a symmetric series (+0.01, −0.01,
  +0.01, −0.01) has Sharpe exactly 0 and, with one recorded shot,
  SR0 exactly 0 — so the deflation is Φ(0) = 0.5, bit for bit;
  doubling every return doubles mean and stdev alike, so the whole
  headline returns identical (the deflation is scale-free); the
  golden run's five equity points give four returns, and its
  declining curve (1000 → 988) deflates below a half; more shots
  strictly raise SR0 and strictly lower the same headline.

### 9.8 The promotion workflow (promotion.py, increment 7)

- **The product rule, enforced rather than stated**: a record
  cannot move to `validated` without held-out, walk-forward,
  sensitivity and critique evidence all recorded (§3's table), and
  the gate re-checks on every construction — a JSON file edited by
  hand into `validated` without those kinds is refused, not read.
  The refusal names exactly what is still missing.
- **Independence is checked, not promised**: a critique recorded by
  the candidate's own author is refused at append time, at
  promotion time, and at load time — the independence half of
  anti-overfitting §2.10 made mechanical; the review process behind
  it remains the documented protocol.
- **Every move states itself**: transitions are append-only, and
  the recorded history is replayed through the same legal-move
  rules on every load — `unregistered → candidates` for
  registration, `candidates → validated / rejected / archived`,
  `validated → archived`, and `rejected` and `archived` terminal. A
  record whose history does not chain, records a move with no path,
  or ends at another stage than the one it claims is refused. A
  rejection and an archive each require a kept reason (§2.9: the
  true number of attempts stays visible), and a validated strategy
  is archived with its reason, never rewritten as never-tried.
- **No live stage exists**: the stage set is candidates, validated,
  rejected, archived; `to_stage="live"` is refused; and no
  transition could reach live consideration — that is Phase 10 plus
  human approval, deliberately outside this machine.
- **Evidence is a reference, never a measurement**: entries are
  (kind, reference, detail, who recorded it, when) over a closed
  kind set with one entry per kind, so nothing can be quietly
  replaced. Run manifests and reports stay artefacts of runs
  outside version control and the record names them by id: nothing
  here can drift from a number it no longer owns, and nothing here
  invents one. Slugs are path-safe by construction (lowercase
  letters, digits, single hyphens) and validated before any path is
  built.
- **The file move loses nothing**: a stage change writes the new
  stage's file first and removes the old one after; the same slug
  in two stages is refused as a duplicate; a listing
  (`iter_records`) raises on a corrupt, misfiled or foreign record
  rather than skipping it. The whole machine is driven by
  `hqos strategy register/evidence/promote/reject/archive/show`.
- Tests: `tests/backtesting/test_promotion.py` walks the golden
  promotion path and every refusal above (missing evidence,
  self-critique at all three layers, empty reasons, closed stages,
  the absent live stage), the byte-for-byte JSON round trip,
  tampered histories, the file move and the duplicate slug; CLI
  coverage lives in `tests/unit/test_cli.py`.
