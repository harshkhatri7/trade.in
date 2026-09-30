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
| `hqos backtest report`                                                        | `../cli.py`           |

Every simulated order is evaluated by `ConfiguredRiskEvaluator`
before it may fill — the same configured gate the paper-trading path
will use. Reports are written to `research/reports/`, which Git
ignores: a simulated result is an artefact of a run, never repository
content. Out-of-sample splitting, walk-forward testing and regime
splits belong to Phase 7 and are **not implemented**.

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
