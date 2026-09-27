# Secrets management

---

## 1. Rules

1. **No secret in a tracked file.** Not in source, tests, docs, config,
   fixtures, commit messages or CI logs.
2. **`.env` is local-only.** It is git-ignored; `.env.example` is the tracked
   template and contains placeholders only.
3. **One reader.** Only `harsh_quant_os.config.Settings` reads environment
   credentials. No scattered `os.environ` access.
4. **Validate on load.** Placeholder values are detected and rejected outside
   `development`/`test`.
5. **Rotate freely.** Each subsystem has its own key so rotation is a
   five-minute operation.
6. **Never log a secret.** Not in full, not in part, not as a hash of a short
   value.

---

## 2. Where secrets live

| Context            | Location                                        | Tracked? |
| ------------------ | ----------------------------------------------- | -------- |
| Local development  | `.env` (repository root)                        | No       |
| Template           | `.env.example`                                  | Yes      |
| CI                 | GitHub Actions secrets/variables                | No       |
| Deployed services  | Platform secret store, injected at start-up     | No       |
| Database           | Dedicated role password, environment-injected   | No       |
| Local agent token  | `.env` on the PC, generated locally             | No       |
| Broker credentials | **Do not exist.** Required only from Phase 15/16 | —       |

---

## 3. Environment variables

The full list with placeholders is in
[`.env.example`](../../.env.example). Groups:

| Group             | Variables (examples)                                       |
| ----------------- | ---------------------------------------------------------- |
| Application       | `APP_ENV`, `LOG_LEVEL`                                      |
| API / Web         | `API_HOST`, `API_PORT`, `API_ALLOWED_ORIGINS`               |
| Authentication    | `AUTH_SECRET_KEY`, `AUTH_TOKEN_EXPIRY_MINUTES`              |
| Database          | `DATABASE_URL`, `DATABASE_PASSWORD`                         |
| Local agent       | `LOCAL_AGENT_TOKEN`, `LOCAL_AGENT_ENABLED`, `LOCAL_AGENT_ALLOWED_ROOTS` |
| Data providers    | `MARKET_DATA_API_KEY`, `HISTORICAL_DATA_API_KEY`            |
| AI                | `AI_API_KEY`, `AI_PROVIDER`, `AI_LOCAL_ENABLED`             |
| Notifications     | `NOTIFICATION_WEBHOOK_URL`, `NOTIFICATION_EMAIL_PASSWORD`   |
| Trading safety    | `LIVE_TRADING_ENABLED` (must be `false`), `BROKER_API_KEY` (empty) |
| Risk defaults     | `RISK_MAX_POSITION_NOTIONAL`, `RISK_MAX_DAILY_LOSS`, …      |
| Cloud sync        | `CLOUD_SYNC_ENABLED`, `CLOUD_STORAGE_BUCKET`                |

---

## 4. Generation

Generate strong values locally; never reuse a value across subsystems.

```powershell
# 32+ random characters, suitable for AUTH_SECRET_KEY or LOCAL_AGENT_TOKEN
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 | ForEach-Object { [char]$_ })
```

```bash
# equivalent on any platform with Python
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the result into `.env`. Never into a commit.

---

## 5. Validation

`Settings` enforces at load time:

- `LIVE_TRADING_ENABLED=true` ⇒ **rejected** (there is no enabling path);
- placeholders present while `APP_ENV` is `staging`/`production` ⇒ rejected;
- `Settings.missing_secrets()` lists any unset credential for diagnostics.

Automated checks:

| Test                                            | Guards against                          |
| ----------------------------------------------- | --------------------------------------- |
| `tests/security/test_env_template.py`           | A real credential appearing in the template |
| `tests/security/test_no_secrets_committed.py`   | Credential-shaped strings anywhere in the tree |
| `tests/security/test_no_secrets_committed.py`   | `.env` losing its git-ignore rule        |

Run them with `npm run test:py`; they also run in CI.

---

## 6. Rotation procedure

1. Generate a new value.
2. Update the local `.env` and/or the platform secret store.
3. Restart the affected service.
4. Revoke the old value.
5. Confirm health with `npm run health`.
6. If the old value was ever committed: **revoke first**, then clean history,
   then report the exposure (see
   [git workflow](../development/git-workflow.md)).

---

## 7. What must never be stored

- Broker API keys and account identifiers (until a reviewed Phase 15 design).
- Password hashes that are trivially reversible, or plaintext passwords.
- Session tokens with no expiry.
- Personal data of any kind beyond an account email.
- Model provider keys in the browser bundle.

---

## 8. Incident response

| Situation                       | First action                              |
| ------------------------------- | ------------------------------------------ |
| Secret committed                | Rotate, then remove, then report           |
| Secret exposed in a log         | Rotate, scrub the log source, add a test   |
| Unknown secret found in the tree| Stop; do not paste it anywhere; report     |
| `.env` accidentally committed   | Rotate everything in it — assume compromise |

Rotation always comes before repository hygiene.
