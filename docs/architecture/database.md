# Database architecture

**Phase:** 2 — Database. PostgreSQL now exists and holds `users`,
`sessions` and `audit_log`; this document remains the agreed design that the
rest of the schema is built to. Sections marked *planned* describe tables
that do not exist yet.

---

## 1. Engine

**PostgreSQL** is the source of truth for everything the platform remembers:
datasets and their provenance, experiments, strategies, trades, journal
entries, model records and audit history.

**TimescaleDB** is a *candidate* extension for hypertables and continuous
aggregates. Adopt it only if measured query patterns justify the dependency;
it is not assumed here. Rationale: avoid a dependency whose benefit has not
been demonstrated.

Local, large or derived artefacts (raw files, feature matrices, model
binaries) live on disk in `data/` with a manifest in PostgreSQL — the database
stores **references and metadata**, not multi-gigabyte blobs.

---

## 2. Schema domains

| Domain       | Core tables (planned)                                                 |
| ------------ | --------------------------------------------------------------------- |
| Identity     | `users`, `sessions`, `roles`, `api_tokens`                            |
| Data         | `datasets`, `dataset_provenance`, `dataset_quality`, `providers`      |
| Research     | `hypotheses`, `experiments`, `experiment_runs`, `artifacts`            |
| Strategy     | `strategies`, `strategy_versions`, `signals`                          |
| Backtest     | `backtest_runs`, `backtest_metrics`, `walk_forward_runs`              |
| Trading      | `orders`, `positions`, `fills`, `journal_entries`                     |
| Risk         | `risk_limits`, `risk_decisions`, `kill_switch_events`                 |
| Memory       | `memory_entries` (partitioned by `MemoryCategory`)                    |
| Jobs         | `jobs`, `job_events`, `audit_log`                                     |

### Memory categories

`MemoryCategory` (already implemented in
`harsh_quant_os.memory`) partitions persistent memory into:
`market`, `strategy`, `experiment`, `trade`, `research`, `journal`,
`model`, `system`.

---

## 3. Provenance columns

Every dataset table carries, or references, the fields enforced by
`harsh_quant_os.contracts.provenance.DatasetProvenance`:

```text
source            provider identifier
symbol            provider-neutral instrument id
timestamp         period covered (timezone aware, UTC)
ingested_at       when the platform ingested it (>= timestamp)
timeframe         tick|1m|5m|15m|30m|1h|4h|1d|1w|1mo
quality_status    unknown|pending|valid|suspect|invalid
provenance        lineage: raw artefact URI / ingestion run id
version           dataset version
```

Rules:

- Rows without provenance are **not** stored.
- `quality_status = invalid` is rejected at the contract level; invalid data
  is quarantined in a separate table, never silently corrected.
- Deleting a dataset requires an audited cascade decision, not a cascade
  from the ORM.

---

## 4. Integrity rules

| Rule                    | Mechanism                                                  |
| ----------------------- | ---------------------------------------------------------- |
| No silent overwrites    | Version columns + append-only history tables               |
| Audit is immutable      | No `UPDATE`/`DELETE` grant on `audit_log` for the app role  |
| Time is always UTC      | `timestamptz` everywhere; application never stores local time |
| Referential honesty     | Foreign keys with deliberate `ON DELETE` policy per table   |
| Numeric exactness       | Money: `numeric(20, 6)` — never `float8`                    |
| Enum safety             | `text` + `CHECK` (or native enums) matching the Pydantic/TS enums |
| Deterministic ordering  | Every list query has an explicit `ORDER BY`                 |

---

## 5. Migrations

- Alembic, forward-only in shared environments.
- Every migration is reviewed like code and is reversible locally by
  restoring a backup.
- `scripts/data/reset-database.ps1` drops and recreates the **local
  development** database only, and refuses to run outside `development`.
- CI runs migrations from empty on every pull request
  (`tests/integration/test_migrations.py`, in the job that carries a
  PostgreSQL service).

---

## 6. Access and credentials

- Connection string comes from `Settings` (environment), never from source.
- Separate roles for migrations (DDL) and application (DML).
- Local dev password is a placeholder; production-like secrets are injected
  at deploy time. See [secrets management](../security/secrets-management.md).
- No personal data is stored beyond an account email and display name.

---

## 7. Backup and recovery

**Not implemented — an open Phase 2 exit criterion.** Nothing in this
repository takes a backup today, so no document may imply otherwise.
Documented intent, in [backup](../operations/backup.md) and
[disaster recovery](../operations/disaster-recovery.md):

- nightly logical dump of the metadata database;
- dataset store backed up separately (local disk → external media/cloud);
- restore rehearsed before Phase 6 results are relied upon.

---

## 8. Phase 2 exit criteria

| Criterion                                                        | Status |
| ---------------------------------------------------------------- | ------ |
| Empty → current migrations run cleanly; rollback path documented | **Met** — `tests/integration/test_migrations.py`, and `npm run db:downgrade` |
| Audit table is append-only                                       | **Met** — trigger plus `CHECK` constraint, both asserted by a test |
| Sessions survive a restart and are covered by tests              | **Met** — `tests/integration/test_auth_http.py` |
| Provenance, experiment, strategy, journal and audit tables exist  | **Partly** — `audit_log` exists; the other four domains do not |
| Money columns are exact-numeric; timestamps are `timestamptz`    | **Partly** — every timestamp that exists is `timestamptz`; no money columns exist yet |
| Application role cannot modify audit rows                        | **Met** — the trigger refuses `UPDATE` and `DELETE` for any role |
| Backup and restore verified once, end to end                     | **Not met** |

Because the last row is unmet, Phase 2 is **not** complete.
