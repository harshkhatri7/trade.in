# Research methodology

How research is conducted in HARSH QUANT OS so that conclusions are earned
rather than selected.

---

## 1. The standard

A research conclusion is only accepted when:

1. it is traceable to specific dataset versions and code versions;
2. it survived a pre-declared evaluation plan;
3. it was tested on data not used to choose it;
4. its limitations are written down next to it;
5. someone else (or a later you) can reproduce it from the record.

Everything else is a **hypothesis**, and is labelled as one.

---

## 2. Lifecycle

```text
HYPOTHESIS → DESIGN → EXPERIMENT → EVIDENCE → CRITIQUE → DECISION → MEMORY
     ▲                                                             │
     └───────────────────── new hypothesis ◄──────────────────────┘
```

| Stage        | Artefact                        | Rule                                             |
| ------------ | ------------------------------- | ------------------------------------------------ |
| Hypothesis   | `research/hypotheses/`          | States the claim, the mechanism, the expected sign |
| Design       | Experiment plan                 | Fixed **before** running: data, period, metrics, success criterion |
| Experiment   | `research/experiments/`         | Reproducible config + data version + code version |
| Evidence     | `research/reports/`             | Results with assumptions and failure modes        |
| Critique     | Peer/agent review               | Actively look for the reason it might be wrong    |
| Decision     | Journal entry                   | Accept, reject or hold — with reasoning           |
| Memory       | Persistent store (Phase 13)     | Database, never conversation history               |

---

## 3. Pre-registration

The evaluation plan is written **before** results exist:

- dataset versions and date range;
- universe definition (as-of, not current membership);
- features and candidate parameters;
- primary metric and the threshold for "interesting";
- number of variants you intend to try;
- what outcome would make you abandon the idea.

Changing the plan after seeing results is allowed — but the change is
recorded, and the result is then marked exploratory, not confirmatory.

---

## 4. Bias register

Every project maintains an explicit list of the biases it might be subject to:

| Bias                    | Where it appears                                   |
| ----------------------- | -------------------------------------------------- |
| Selection               | Trying many ideas, reporting the winner            |
| Look-ahead              | Using information that did not exist yet           |
| Survivorship            | Universe built from today's survivors              |
| Data snooping           | Reusing the same history for many questions        |
| Publication             | Only "good" results reaching reports               |
| Regime                  | Conclusion specific to one market regime           |
| Transaction-cost optimism | Ignoring impact, borrow, or capacity             |
| Implementation          | Backtest fills that real execution could not match |

The countermeasures live in [anti-overfitting](anti-overfitting.md) and
[backtesting methodology](backtesting-methodology.md).

---

## 5. Experiment protocol summary

Full detail: [experiment protocol](experiment-protocol.md).

1. Register the hypothesis and success criterion.
2. Pin dataset versions.
3. Run the training/selection phase.
4. Evaluate once on held-out data.
5. Run walk-forward analysis.
6. Record everything, including failed attempts.
7. Write the report with limitations in the first paragraph.

---

## 6. Recording negative results

Rejected and failed ideas are **kept** in `strategies/rejected/` with the
reason. Deleting them recreates the selection bias they were meant to expose.

A rejected hypothesis with a clear reason is more valuable than an untracked
success.

---

## 7. What research is not

- Not a search for a number that looks good.
- Not a backtest tuned until the curve is attractive.
- Not a claim about future returns.
- Not something that lives only in a chat transcript.

Past performance does not indicate future results, and no document in this
repository may present it as if it did.

---

## 8. Current state

Phase 0 provides the documentation structure only: `research/experiments/`,
`research/hypotheses/`, `research/reports/`, `research/notebooks/`. No
experiments have been run. See
[../PROJECT-STATUS.md](../PROJECT-STATUS.md).
