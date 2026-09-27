# Synchronization architecture

**Phase:** 0 — Foundation. **Synchronization is not implemented (Phase 12).**

---

## 1. The split

| Tier        | Holds                                                   | Why                                   |
| ----------- | ------------------------------------------------------- | ------------------------------------- |
| **Cloud**   | Web UI, API, authentication, PostgreSQL metadata, lightweight jobs, notifications | Always available, small state, shared |
| **Local PC**| Heavy backtests, large datasets, ML experiments, local models, research, training | Compute and storage stay where the data is |

The **local agent** is the controlled bridge. Synchronization moves
*metadata, manifests and small artefacts*; it is not a file-sync product.

---

## 2. What is synchronised

```text
CLOUD                              LOCAL
─────                              ─────
project metadata            ◄──►  experiment configs
job definitions / status     ◄──►  job results (summaries, manifests)
dataset manifest (versions) ◄──►  dataset files (raw, clean, features)
research memory              ◄──►  research memory replicas
notifications / alerts       ──►  local job events
```

What is **never** synchronised:

- secrets, tokens, `.env` files;
- broker credentials (none exist);
- audit logs in a mutable form (replicas are read-only);
- anything the local agent's path allow-list does not cover.

---

## 3. Design rules

1. **Metadata is authoritative in the cloud; bytes are authoritative locally.**
   The database holds the manifest; the PC holds the files.
2. **Versioned, not overwritten.** Every syncable object carries a version;
   conflicting versions are both retained and reconciled explicitly.
3. **Idempotent.** Re-running a sync produces the same state; interrupted
   transfers resume safely.
4. **Integrity checked.** Content hashes are verified on both sides; a hash
   mismatch quarantines the object and raises a notification.
5. **Resumable and observable.** Progress, failures and remaining items are
   queryable; sync state is a first-class UI concept.
6. **Consent-driven upload.** Large local datasets leave the PC only when the
   operator has selected them.
7. **Conflict policy is explicit.** Local work is never silently discarded;
   a conflict creates a record requiring a decision.

---

## 4. Transport

```text
LOCAL AGENT ──(authenticated, TLS)──► API sync endpoint ──► PostgreSQL + object storage
```

- The local agent authenticates with its own credentials, not a user session.
- Transfer is chunked and resumable; each chunk carries the object version.
- Rate and bandwidth limits are configurable so sync never starves local
  research work.

---

## 5. Notifications

Small, event-driven notifications (job finished, sync conflict, risk limit
reached, dataset quarantined) are a **cloud** concern: email or webhook,
configured in `Settings`, disabled by default
(`NOTIFICATIONS_ENABLED=false`).

Notifications never contain secrets or full dataset contents.

---

## 6. Current state and exit criteria

**Phase 0:** configuration keys exist (`CLOUD_SYNC_ENABLED=false`,
`CLOUD_STORAGE_BUCKET`, `CLOUD_REGION`); no sync code.

**Phase 12 exit criteria:**

- Manifest-based sync with content hashes and version checks.
- Idempotent and resumable, proven by an interrupted-transfer test.
- Conflicts recorded, never silently resolved.
- Secrets provably excluded from every sync payload.
- End-to-end test covering cloud → local → cloud round trip.
