# Monitoring

**Status:** Phase 0. There is no running service to monitor yet. This
document defines what will be observed and how honestly it will be reported.

---

## 1. Principles

1. **Measure reality.** Metrics come from the system, never from estimates.
2. **Silence is not health.** A monitor that stops reporting is itself an
   alert.
3. **Alerts are actionable.** Every alert names an owner and a response.
4. **No vanity metrics.** If a number cannot change a decision, do not chart it.
5. **Logs never contain secrets** — verified by review and by tests.

---

## 2. What to observe

### Application
| Signal                     | Why                                                        |
| -------------------------- | ---------------------------------------------------------- |
| Request rate / latency     | Is the API healthy and responsive?                         |
| Error rate by status       | Degrade detection (5xx vs. 4xx)                            |
| Auth failures              | Brute force or misconfiguration                            |
| Job queue depth / age      | Are local jobs running or stuck?                           |
| Job failure rate           | Agent health and data problems                             |

### Data
| Signal                          | Why                                                   |
| ------------------------------- | ----------------------------------------------------- |
| Ingestion runs: success/failure | Detect provider or pipeline breakage                  |
| Dataset quality distribution    | Growth of `suspect`/`invalid` is a leading indicator  |
| Gap count per dataset           | Unexpected holes in history                           |
| Freshness (last `ingested_at`)  | Stale data feeding research                           |

### Research
| Signal                          | Why                                                   |
| ------------------------------- | ----------------------------------------------------- |
| Backtest runs and durations     | Cost and capacity planning                            |
| Reproducibility check failures  | Silent drift in engines or data                       |
| Out-of-sample vs. in-sample gap | Overfitting signal (Phase 7+)                         |

### Safety
| Signal                          | Why                                                   |
| ------------------------------- | ----------------------------------------------------- |
| Trade-gate rejections           | Strategies attempting disallowed actions              |
| Kill-switch events              | Immediate operator attention                          |
| Risk-limit breaches             | Trend analysis and incident review                    |
| Configuration changes           | Who changed what, and when                            |
| Live-trading flag tampering attempts | Must be zero; any event is an incident            |

### Infrastructure
| Signal                          | Why                                                   |
| ------------------------------- | ----------------------------------------------------- |
| CPU / memory / disk             | Local compute headroom                                |
| Database connections / locks    | Contention and exhaustion                             |
| Backup success and age          | Stale backups are silent failures                     |
| Dependency audit results        | New advisories                                        |

---

## 3. Logging

- Structured JSON with `timestamp`, `level`, `component`, `request_id`,
  `job_id`, `principal`.
- Levels driven by `LOG_LEVEL`.
- Rotation and retention in `logs/` (git-ignored).
- Redaction of tokens, keys, passwords and payload bodies is mandatory.

---

## 4. Alerting

| Severity | Examples                                        | Response                    |
| -------- | ----------------------------------------------- | --------------------------- |
| Critical | Backup failing, audit write failing, live-flag tampering, database down | Immediate human attention |
| High     | Ingestion failing, job queue stalled, error-rate spike | Same working day         |
| Medium   | Rising `suspect` data share, slow queries       | Review within a week        |
| Low      | Dependency advisory, coverage regression        | Next maintenance window     |

Notifications are configured through `Settings`
(`NOTIFICATIONS_ENABLED=false` by default) and are documented in
[deployment](deployment.md).

---

## 5. Dashboards (Phase 12+)

- **Service health**: API latency, errors, jobs.
- **Data health**: freshness, quality, gaps.
- **Research**: runs, durations, reproducibility.
- **Safety**: gate rejections, risk events, configuration changes.

Dashboards display state, not aspiration: a panel that cannot be populated
says "no data", it does not show zero.

---

## 6. What exists today

Only the local health report:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\development\health-check.ps1
```

It reports **real** results for Git, Node, Python, dependencies, the virtual
environment, Docker availability and repository cleanliness — and reports
`UNKNOWN`/`MISSING` when something could not be checked. It never prints a
success it did not observe.
