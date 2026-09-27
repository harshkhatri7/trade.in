# Experiment protocol

The checklist every experiment must complete before its results count as
evidence.

---

## 1. Before running

- [ ] Hypothesis written in `research/hypotheses/` with mechanism and expected sign.
- [ ] Success criterion and metric fixed in advance.
- [ ] Number of intended variants recorded.
- [ ] Dataset **versions** pinned (not "latest").
- [ ] Universe defined as-of the simulation date.
- [ ] Time period, timeframe and timezone stated.
- [ ] Cost and slippage models chosen and parameterised.
- [ ] What would falsify the hypothesis is written down.
- [ ] Random seeds fixed and recorded, if any randomness is involved.

## 2. While running

- [ ] Configuration captured verbatim (code + data + parameters).
- [ ] Every attempt recorded — successes **and** failures.
- [ ] No edits to the plan without appending a dated change note.
- [ ] Held-out data accessed only at the designated step, once.
- [ ] Resource usage logged (runtime, memory) for cost awareness.

## 3. After running

- [ ] Results stored under `research/experiments/` with the manifest.
- [ ] Held-out evaluation performed and reported separately.
- [ ] Walk-forward results included.
- [ ] Parameter sensitivity surface included.
- [ ] Benchmark and shuffled-signal null included.
- [ ] Regime breakdown included.
- [ ] Trade count and confidence intervals shown.
- [ ] Limitations listed in the **first** paragraph of the report.
- [ ] Reproducibility check: re-ran from the manifest and matched the numbers.

## 4. Review

- [ ] Quant agent review: maths, timing, leakage.
- [ ] Auditor agent review: is the claim supported by the evidence attached?
- [ ] Decision recorded: **accept**, **reject**, or **hold** — with reasons.
- [ ] Outcome filed in persistent memory (Phase 13) with provenance.
- [ ] Candidate moved to `strategies/candidates/`, `validated/` or `rejected/`.

## 5. Reporting template

```text
EXPERIMENT   <id>
HYPOTHESIS   <claim + mechanism + expected sign>
DATA         <provider, dataset versions, timeframe, period, universe>
METHOD       <rules, parameters, seeds, cost/slippage models>
RESULT       <primary metric, benchmark, trade count, drawdown>
ROBUSTNESS   <out-of-sample, walk-forward, sensitivity, regimes, null>
LIMITATIONS  <biases present, sample size, assumptions — first, not last>
REPRODUCE    <command + manifest path>
DECISION     <accept | reject | hold, with reasoning>
AUTHOR       <agent/human, date>
```

---

## 6. Rules that are not negotiable

1. No result without a manifest.
2. No manifest without pinned dataset versions.
3. No claim without its limitations.
4. No silent plan changes.
5. No deleted failed attempts.
6. No absolute statement about future outcomes.

---

## 7. Current state

Phase 0 provides the protocol and the directory layout
(`research/experiments`, `research/hypotheses`, `research/reports`,
`research/notebooks`). No experiment has been registered or run. See
[../PROJECT-STATUS.md](../PROJECT-STATUS.md).
