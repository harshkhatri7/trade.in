# Backup

**Status:** Phase 0 — no database and no deployed environment yet. The policy
below defines what will be protected from Phase 2 onwards.

---

## 1. What must be protected

| Data                          | Location                | Why it matters                                   |
| ----------------------------- | ----------------------- | ------------------------------------------------ |
| Metadata database             | PostgreSQL              | Provenance, experiments, strategies, journal, audit |
| Raw + cleaned datasets        | `data/raw`, `data/clean`| Expensive or impossible to re-acquire            |
| Feature matrices + recipes    | `data/features`         | Reproducibility of research                      |
| Backtest manifests and reports| `research/reports`      | Evidence behind conclusions                      |
| Trading journal               | database                | Decision history                                 |
| Configuration (non-secret)    | repository              | Rebuildable, but versioned                       |

**Never backed up:** `.env`, credentials, secrets, `node_modules`, `.venv`,
caches.

---

## 2. Backup tiers

| Tier     | Scope                                  | Frequency      | Retention |
| -------- | -------------------------------------- | -------------- | --------- |
| Hot      | Metadata database logical dump         | Nightly        | 30 days   |
| Warm     | Dataset store snapshot (local disk)    | Weekly         | 4 copies  |
| Cold     | Full off-machine copy (external/cloud) | Monthly        | 12 copies |
| On-demand| Before any migration or upgrade        | Every time     | Until verified |

Backups are stored **separately** from the machine holding the primary copy —
a backup on the same disk is not a backup.

---

## 3. Principles

1. **Backups are useless until restored.** Every backup scheme is tested by
   performing a restore, on a clean environment, and verifying the data.
2. **Secrets stay out.** A backup containing credentials is a liability; it
   never does.
3. **Append-only history is included.** Audit logs must survive in order.
4. **Automation with honest reporting.** A failed backup raises a
   notification; silence is treated as failure.
5. **Documented recovery time.** Each tier states its expected restore time
   once measured — not before.

---

## 4. Planned procedure (Phase 2)

```text
pg_dump (custom format, compressed)
  → timestamped archive
  → integrity hash written alongside
  → copy to off-machine storage
  → retention pruning
  → notification with real result
```

For the dataset store: a manifest-driven copy, verifying each file's hash
after transfer.

Scripts will live in `scripts/maintenance/` and will print real success or
real failure — never an unconditional success message.

---

## 5. Restore procedure (rehearsed)

1. Pick a backup point; verify its hash.
2. Restore into an **empty** database/directory.
3. Run migrations to the current version.
4. Verify: row counts, the oldest audit record, one known dataset hash, and
   one known experiment.
5. Record the measured recovery time.

---

## 6. Verification schedule

| When                        | Action                                      |
| --------------------------- | ------------------------------------------- |
| Weekly                      | Confirm the nightly dump succeeded          |
| Monthly                     | Restore into a scratch environment          |
| Before every migration      | Take and verify an on-demand backup         |
| Every phase exit            | Confirm backup and restore are still working |

---

## 7. What is *not* covered yet

- No database exists (Phase 2), so no dump runs today.
- Docker is not installed on the development machine, so no local PostgreSQL
  is provisioned.
- Cloud object storage is configured in Phase 12.

Track these in [../PROJECT-STATUS.md](../PROJECT-STATUS.md).
