# Threat model

Scope: HARSH QUANT OS at Phase 0 and as it will exist through Phase 17.
Method: assets → trust boundaries → adversaries → mitigations → residual risk.

---

## 1. Assets worth protecting

| Asset                              | Impact if lost or altered                              |
| ---------------------------------- | ------------------------------------------------------ |
| Credentials (data, AI, notification, local agent) | Unauthorised access, cost, data exposure |
| Research data and provenance       | Corrupted conclusions, undetectable manipulation        |
| Experiment / strategy history      | Rewritten history, unjustified confidence               |
| Audit log                          | Unattributable actions, no accountability               |
| Risk configuration                 | Unbounded losses                                        |
| Local filesystem (via the agent)   | Full compromise of the researcher's PC                  |
| Trading decisions                  | Financial loss; with live trading, real money           |
| Reputation of results              | Acting on fabricated or leaked figures                  |

---

## 2. Trust boundaries

```text
B1  Browser            → API            (untrusted client)
B2  API                → Database       (least-privilege role)
B3  API                → Local agent    (token + job allow-list)
B4  Local agent        → Local FS       (path allow-list)
B5  Strategy code      → Risk engine    (one-way: request only)
B6  Risk engine        → Trade gate     (one-way: approval only)
B7  Any code           → Secrets        (via Settings only)
B8  AI adapter         → Any tool       (typed allow-list only)
```

---

## 3. Adversaries

| Adversary                     | Capability assumed                                            |
| ----------------------------- | -------------------------------------------------------------- |
| Opportunistic attacker        | Sees a public endpoint, tries known exploits                  |
| Malicious data provider       | Controls returned data, may try to inject payloads            |
| Prompt injector               | Controls text a model reads (headlines, notes, tool output)   |
| Compromised dependency        | Executes code during install or at import time                |
| Curious AI agent              | Follows instructions embedded in data or context              |
| Insider / operator error      | Well-intentioned but makes a destructive mistake              |
| The system itself             | Bugs, races, partial writes, clock skew                       |

---

## 4. Threats and mitigations

| # | Threat                                             | Mitigation                                                    | State |
| - | -------------------------------------------------- | ------------------------------------------------------------- | ----- |
| T1 | Secret committed to the repository                 | `.gitignore`, `.env.example` placeholders, secret-scan test, CI | Enforced |
| T2 | Live trading enabled by mistake                    | `Settings` rejects the flag; gate raises; tests fail the build | Enforced |
| T3 | Strategy bypasses risk                             | Architectural separation; separate packages; property tests   | Phase 9 |
| T4 | Browser gains filesystem access                    | Only API → agent path; agent path allow-list; no shell        | Phase 11 |
| T5 | Local agent abused as a remote code executor       | Typed operation allow-list; no command strings, ever          | Phase 11 |
| T6 | Path traversal / symlink escape on the agent       | Canonicalisation + prefix check with adversarial tests        | Phase 11 |
| T7 | Stolen session/token                               | Short-lived tokens, rotation, revocation, audit               | Phase 1 |
| T8 | SQL injection                                      | Parameterised queries via SQLAlchemy; no string-built SQL     | Phase 2 |
| T9 | Poisoned or manipulated data                       | Provenance, cross-source checks, `suspect` status, quarantine | Phase 3 |
| T10 | Look-ahead / leakage producing false confidence    | Deterministic tests, leakage properties, manifest reproducibility | Phase 6/7 |
| T11 | Prompt injection steering research or tooling      | Model output treated as data; typed tool allow-list; human confirmation for writes | Phase 8 |
| T12 | Dependency supply-chain compromise                 | Lockfiles, `npm audit`, reviewed install scripts, pinned images | Ongoing |
| T13 | Audit history edited                               | Append-only table, no application path to UPDATE/DELETE       | Phase 9 |
| T14 | Runaway job exhausts the PC                        | Concurrency limits, timeouts, cancellation, output caps       | Phase 11 |
| T15 | Secrets leaking into logs                          | Structured logging without payloads; log review; tests        | Phase 1 |
| T16 | Backup contains credentials                        | Backups store data only; secrets stay in the secret store     | Phase 2 |
| T17 | Clock skew breaking causality                      | UTC storage, explicit ordering, session calendars             | Phase 3/6 |
| T18 | Unbounded human error (fat finger)                 | Order rate limits, position caps, kill switch, human approval | Phase 9/10 |

---

## 5. Explicit non-goals

- Protecting against an attacker with administrative control of the local PC.
- Anonymity or anti-forensics.
- Multi-tenant isolation (single private operator).
- Availability guarantees for third-party data providers.

---

## 6. Residual risks at Phase 0

| Risk                                              | Handling                                        |
| ------------------------------------------------- | ------------------------------------------------ |
| No authentication exists yet — nothing is exposed | Not scheduled until Phase 1; no listener exists  |
| Docker absent, so local PostgreSQL unprovisioned  | Documented in project status; optional           |
| Dependency advisories may appear after install    | CI runs `npm audit`; refresh on notice           |
| Git identity is a local placeholder               | Must be set before pushing to a remote           |
| Single-machine, single-operator key material      | Acceptable at this scale; revisit before Phase 16 |

---

## 7. Review cadence

- Every security-relevant change: reviewed by the **Security** agent.
- Every phase exit: threat model updated with the new boundaries.
- Before Phase 15/16: full model review, including broker credential design
  ([broker security](broker-security.md)).
