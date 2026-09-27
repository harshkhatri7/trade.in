# Deployment

**Status:** Phase 0. Nothing is deployed; there is no production environment
and no remote Git repository. This document defines the target.

---

## 1. Environments

| Environment | Contents                                   | Live trading | Secrets           |
| ----------- | ------------------------------------------ | ------------ | ----------------- |
| development | Local machine, `.venv`, npm workspaces, optional Docker PostgreSQL | Disabled | `.env`, placeholders OK |
| test        | CI runners, ephemeral database             | Disabled     | Test-only values  |
| staging     | Cloud web + API + database                 | Disabled     | Injected at deploy|
| production  | Cloud web + API + database                 | Disabled until Phase 16 | Platform secret store |

No environment enables live trading. Enabling it is a Phase 16 activity with
its own approval process, not a deployment flag.

---

## 2. Target topology

```text
CLOUD
  ├── CDN / edge
  ├── Web (Next.js)            static + server rendering
  ├── API (FastAPI + Uvicorn)  behind TLS, private DB access
  ├── PostgreSQL               managed, encrypted at rest, daily backups
  ├── Object storage           dataset manifests and small artefacts
  └── Job queue                lightweight cloud jobs only

LOCAL PC
  ├── Local agent              loopback, token-authenticated
  ├── Dataset store            raw/clean/features
  └── Compute                  backtests, ML, local models
```

Rationale and details: [system architecture](../architecture/system-architecture.md)
and [synchronization](../architecture/synchronization.md).

---

## 3. Deployment mechanism

Phase 1–11: manual/semi-automated, documented, reversible.

- Infrastructure described as code under `infrastructure/deployment/`.
- Containers built from `infrastructure/docker/` with pinned base images.
- Configuration injected from the platform secret store at start-up — no
  secrets baked into images.
- Database migrations run as a distinct, reviewable step before new code
  serves traffic, and are backward compatible with the previous release.
- Rollback = redeploy the previous image **and** confirm migration
  compatibility.

CI (`.github/workflows/ci.yml`) only builds and validates. **CI never
deploys.**

---

## 4. Release procedure

1. Green CI on `main`.
2. Version bumped consistently in `package.json`, `pyproject.toml`,
   `version.py`, `CHANGELOG.md`.
3. Tag created.
4. Deploy to staging; run smoke tests (health, auth, one read path).
5. Human approval.
6. Deploy to production; watch logs and error rates.
7. Record the release in the changelog.

---

## 5. Pre-deployment checklist

- [ ] All checks green in CI; no skipped or quarantined security tests.
- [ ] `npm audit` clean, or accepted risks documented.
- [ ] Migrations reviewed and tested from an empty database.
- [ ] Secrets present in the platform store; none in the image.
- [ ] `LIVE_TRADING_ENABLED` is `false` in every environment.
- [ ] Local agent disabled in cloud instances.
- [ ] Backup verified **before** the release, not after.
- [ ] Rollback steps written down.

---

## 6. Post-deployment verification

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\development\health-check.ps1
```

Then verify explicitly:

- health endpoint returns the expected version;
- a real login round trip works;
- a representative read returns traceable data;
- error logs contain no secrets;
- no unexpected outbound connections.

Record what was actually run. If a step could not be executed, it is
reported as not run.

---

## 7. Out of scope

- Deploying anything that can trade live.
- Zero-downtime guarantees (not yet required).
- Multi-region failover (Phase 17 consideration).
- Automated production deploys from CI.
