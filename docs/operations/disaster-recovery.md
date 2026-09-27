# Disaster recovery

**Status:** Phase 0. There is no production system yet; this document defines
the objectives and procedures that apply once there is.

---

## 1. Recovery objectives

| Metric                    | Target (to be measured, not assumed) |
| ------------------------- | ------------------------------------ |
| RPO — acceptable data loss| ≤ 24 hours for metadata; ≤ 1 week for datasets |
| RTO — time to recover     | ≤ 4 hours for cloud services; ≤ 1 day for full local research environment |
| Verification              | Recovery is only "successful" after data checks pass |

Targets are revised once real restore timings exist. They are not
promises before they are measured.

---

## 2. Scenarios

| # | Scenario                                   | Primary response                                             |
| - | ------------------------------------------ | ------------------------------------------------------------ |
| D1 | Corrupted or deleted database row/table     | Restore from the nightly dump into a scratch DB, diff, apply missing rows, audit the cause |
| D2 | Accidental data deletion on the local PC    | Recover from the dataset snapshot; re-ingest if unavailable; record provenance for the recovery |
| D3 | Development machine failure                 | Rebuild from Git + `.env.example` (secrets from your password manager) + dataset store backup |
| D4 | Git repository loss/corruption              | Re-clone from the remote; if no remote exists, restore the `.git` directory from backup |
| D5 | Ransomware / destructive event              | Isolate, restore from cold copies, rotate **all** credentials, review audit logs |
| D6 | Dependency or supply-chain compromise       | Pin and rebuild from lockfiles, audit changes, rotate any credential that could have been exposed |
| D7 | Cloud provider outage                       | Degrade gracefully: local research continues; notify; no data loss expected |
| D8 | Local agent compromise                      | Disable the agent, rotate its token, review job audit records, quarantine affected outputs |
| D9 | Backup itself is unusable                   | Treat as an incident; re-establish backups first, then recover data from the next available copy |

---

## 3. Priority of recovery

```text
1. Credentials   (rotate first — always)
2. Metadata database (provenance, experiments, journal, audit)
3. Raw datasets
4. Derived data  (features — can be recomputed from raw + recipe)
5. Environment   (Git, dependencies, configuration)
```

Nothing is trusted after a compromise until it is verified. Assume any
credential that lived on an affected system is compromised.

---

## 4. Runbooks

### Database recovery
1. Stop writers.
2. Verify the dump's integrity hash.
3. Restore into an empty database.
4. Run migrations; expect none missing.
5. Spot-check counts, oldest audit entry, one dataset hash.
6. Switch the application to the restored database.
7. Record the incident and the measured RTO.

### Local environment recovery
1. Install prerequisites (Git, Node, Python 3.12) — versions in
   [../PROJECT-STATUS.md](../PROJECT-STATUS.md).
2. Clone the repository; run `scripts\setup\setup.ps1`.
3. Restore `.env` from your secret store — never from Git.
4. Restore `data/` from the dataset snapshot; verify hashes against the
   manifest.
5. Run `scripts\development\health-check.ps1` and the full test suite.

### Credential compromise
1. Revoke/rotate immediately.
2. Check audit logs for misuse.
3. Only then investigate how it leaked.

---

## 5. Communication

- Internal: record what happened, when, what was affected, what was restored,
  and what remains uncertain.
- Never publish secrets, keys, dataset contents or personal data in an
  incident note.
- Report uncertainty honestly — "not yet verified" beats a confident guess.

---

## 6. Exercises

| Frequency            | Exercise                                             |
| -------------------- | ---------------------------------------------------- |
| Monthly              | Restore the metadata dump into a scratch database    |
| Quarterly            | Rebuild the development environment from scratch     |
| Before Phase 6 exit  | Prove research reports can be regenerated from manifests |
| Before Phase 16      | Full recovery rehearsal plus credential rotation drill |

---

## 7. Gaps today

- No database yet (Phase 2) → no dump to restore.
- No off-machine backup configured yet.
- No remote Git repository yet (scenario D4 currently has a single copy).

All three are tracked in [../PROJECT-STATUS.md](../PROJECT-STATUS.md).
