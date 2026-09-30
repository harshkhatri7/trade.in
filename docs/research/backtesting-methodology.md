# Backtesting methodology

How backtests are built, run and reported in HARSH QUANT OS.
Architecture detail: [backtesting architecture](../architecture/backtesting.md).

---

## 1. The claim a backtest supports

A backtest answers one narrow question:

> "Given this dataset, this period, this cost model and these rules, what
> would have happened?"

It does not answer "what will happen". Reports are written accordingly.

---

## 2. Simulation rules

| Aspect              | Rule                                                            |
| ------------------- | ---------------------------------------------------------------- |
| Data                | Validated datasets only, versions pinned in the run manifest     |
| Causality           | An order at time *t* uses only information available before *t*   |
| Bar ordering        | Documented and fixed; intrabar assumptions stated explicitly     |
| Costs               | Commission, fees and borrow modelled explicitly, recorded         |
| Slippage            | Named model with parameters; never an implicit zero               |
| Sizing              | Explicit rule; defaults are visible, not hidden                  |
| Partial fills       | Modelled or explicitly excluded — stated either way               |
| Corporate actions   | Adjusted consistently with the dataset version                    |
| Cash                | Exact numerics; no floating-point money                           |
| Starting capital    | Declared (paper: ₹1,000 by default)                               |

---

## 3. Run manifest

Every run records:

```text
run_id · git sha · engine version · dataset versions · universe (as-of) ·
parameters · cost model + inputs · slippage model + inputs · seed ·
start/end · timezone · result artefact hashes
```

Re-executing a manifest must reproduce the numbers. Failure to reproduce is
treated as a defect in the engine or the data — investigated, not explained
away.

---

## 4. Metrics reported

Always:

- total and annualised return, with the compounding convention stated;
- volatility, Sharpe (with its frequency and risk-free assumption stated);
- maximum drawdown and time under water;
- number of trades and median holding period;
- turnover and total costs paid;
- exposure (gross/net) and concentration;
- hit rate **with** the distribution of win/loss sizes.

Reported alongside:

- in-sample vs. out-of-sample, clearly separated;
- confidence intervals or bootstrapped ranges where the sample is small;
- the number of variants tried (multiple-testing context).

A metric without its assumptions is not reported.

---

## 5. Failure modes the methodology must catch

| Failure                 | Detection                                                       |
| ----------------------- | --------------------------------------------------------------- |
| Look-ahead              | Automated causality assertions; feature timing tests            |
| Leakage                 | Split-integrity checks; fit-scope assertions                    |
| Survivorship            | Universe membership as-of the simulation date                   |
| Selection bias          | Pre-registration; recording every attempt; adjusted metrics     |
| Overfitting             | Out-of-sample + walk-forward + parameter sensitivity            |
| Regime dependence       | Results split by regime                                         |
| Cost optimism           | Sensitivity analysis across cost/slippage assumptions           |
| Small samples           | Trade count thresholds; wide confidence intervals flagged       |

---

## 6. Reporting rules

- State limitations **first**, not last.
- Separate measured results from assumptions.
- Use conditional language: "under these assumptions", "in this sample".
- Never present a backtest as evidence of future performance.
- Attach the manifest so the reader can reproduce the run.
- Charts are labelled with dataset version and period.

Blocked phrasing is enforced machine-side in
`tests/unit/test_documentation.py`.

---

## 7. Promotion path

```text
backtest → out-of-sample → walk-forward → parameter sensitivity
        → paper trading (Phase 10) → live consideration (Phase 16, human approval)
```

A backtest never skips directly to trading, and no amount of backtesting
substitutes for paper evidence.

---

## 8. Current state

Implemented for Phase 6 in `src/harsh_quant_os/backtesting/`:

- **§1/§2** — deterministic engine: next-bar-open fills with explicit
  `Decimal` commission and slippage, a bounded history view that
  cannot read past the current bar, and the configured risk evaluator
  consulted for every simulated order;
- **§3** — `manifest.py`: a content-hash `run_id`, no wall clock
  anywhere, byte-identical re-execution, and `ReproductionMismatch`
  when an artefact hash moves (a defect, investigated — never
  explained away);
- **§4** — `metrics.py`: the always-reported set with its assumptions
  attached; an undefined figure renders `None` with the reason stated,
  never a plausible-looking number;
- **§5** — the detections that exist today: look-ahead (causality
  assertions per fill), leakage (version-pinned, re-hashed datasets),
  survivorship (single-instrument membership recorded as-of in the
  manifest), cost optimism (`cost_sensitivity` re-runs the same
  strategy at 0.5x/1x/2x) and small samples (the trade-count threshold
  is named where it is used). Regime splits, walk-forward results and
  multiple-testing adjustment need Phase 7's workflow and are **not
  implemented** — the report states that the number of variants tried
  was not recorded rather than implying it was;
- **§6** — `report.py`: limitations first, the manifest attached,
  assumptions separated from measured results, conditional language
  and the standard caveat. `tests/backtesting/test_report.py` asserts
  each rule, including that generated text contains none of the
  `FORBIDDEN_CLAIMS` phrases.

Run it with `hqos backtest report --dataset <name>`; the report lands
in `research/reports/`, which is Git-ignored — simulated results are
never committed. Reproducing a run is `run_from_manifest` against the
manifest the report attaches.
