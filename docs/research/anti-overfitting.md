# Anti-overfitting

Overfitting is the default failure mode of quantitative research: an
explanation of the past that has no predictive content. This document
defines the countermeasures.

---

## 1. Why it happens here specifically

- Many ideas are tried; the good-looking ones are remembered.
- Parameters are tuned against the same history used to judge them.
- Data is reused across questions until it becomes exhausted.
- Market regimes change, so yesterday's fit can be meaningless tomorrow.
- Reporting favours results that confirm the idea.

---

## 2. Controls

### 2.1 Pre-registration
Write the hypothesis, metric, success threshold and intended number of
variants **before** running anything. See
[research methodology](research-methodology.md).

### 2.2 Data separation
```text
train (selection) → validation → held-out test → walk-forward → paper
```
The held-out set is touched **once**. Repeatedly consulting it converts it
into training data; the protocol records every access.

### 2.3 Walk-forward testing
Rolling or expanding windows; parameters re-fit inside each window; results
aggregated across windows. A single in-sample fit is never reported as the
headline.

### 2.4 Parameter sensitivity
Report the **surface**, not the optimum. A strategy that only works at
exactly `n=17, window=43` is not robust. Adjacent-parameter performance is
part of the result.

### 2.5 Multiple-testing adjustment
Record every variant attempted. Apply deflated performance measures so the
headline number accounts for how many shots were taken.

### 2.6 Benchmarks and nulls
Compare against:
- a passive benchmark of the same universe;
- a randomly-timed (shuffled) version of the same signals — if the shuffled
  version performs similarly, the edge is noise.

### 2.7 Regime robustness
Split results by volatility/trend/liquidity regime. A strategy that only
works in one regime is reported as regime-specific, not as general.

### 2.8 Complexity budget
Prefer fewer parameters and simpler rules. Every additional degree of freedom
must justify itself against the risk it adds.

### 2.9 Negative-result retention
Rejected candidates stay in `strategies/rejected/` with reasons, so the true
number of attempts remains visible.

### 2.10 Independent critique
Before a strategy is marked validated, the Quant and Auditor agents review it
specifically looking for the reason it might be wrong.

---

## 3. Promotion gates

| Stage            | Minimum evidence                                                |
| ---------------- | --------------------------------------------------------------- |
| `candidates/`    | A registered hypothesis and one exploratory run                  |
| `validated/`     | Held-out test + walk-forward + sensitivity + critique, all recorded |
| Live consideration | Everything above **plus** paper-trading evidence (Phase 10) and human approval |

There is no shortcut between these, and none of them implies a return.

---

## 4. Signals that you are already overfitting

- Performance collapsed the moment you changed one parameter.
- The result depends on a data period you already spent time looking at.
- You are adding features to explain residuals.
- The trade count is small enough that a handful of trades drive everything.
- Costs, if modelled honestly, erase the result.
- You cannot state what would falsify the hypothesis.

Any of these sends the work back to `hypotheses/`, not forward.

---

## 5. What we deliberately do not do

- Tune on the test set.
- Report the best of many runs without saying how many were tried.
- Present a backtest as evidence of future performance.
- Hide failed attempts.

---

## 6. Current state

These rules are implemented incrementally with the validation work of
Phases 6 and 7. As of Phase 7 increment 4, data separation (§2.2),
walk-forward testing (§2.3), parameter sensitivity (§2.4) and regime
robustness (§2.7) exist in `src/harsh_quant_os/backtesting/` with
golden tests. The benchmark and shuffled-signal nulls (§2.6) exist
as of Phase 7 increment 5. Multiple-testing adjustment (§2.5) exists
as of Phase 7 increment 6: `deflated.py`'s deflated Sharpe takes the
recorded shot count explicitly (there is no default count) and prices
it into the headline, and the report renders the count when one is
supplied and says "not recorded" when none is — the count is a
record claim, never a guess (backtesting.md §9.7). The promotion
gates (§3) exist as of Phase 7 increment 7: `promotion.py` moves a
record through candidates / validated / rejected / archived,
refuses `validated` without all four recorded kinds, refuses a
critique recorded by the candidate's own author (the independence
half of §2.10, checked rather than promised), keeps a stated reason
on every rejection and archive (§2.9's retention, the file's part
of it), and offers no stage or transition toward live at all
(backtesting.md §9.8). §2.1 pre-registration, §2.8's complexity
budget and the review process behind §2.10 remain documented
protocols here rather than automation. Records hold references and
reasons, never measurements: a backtest's artefacts are run
manifests and reports, which stay outside version control — and
since real research has registered no candidate yet, the repository
currently holds no strategy record at all (backtesting.md §7).
