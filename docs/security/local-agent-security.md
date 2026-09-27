# Local agent security

The local agent is the only component with access to the researcher's PC. It
is therefore the most hardened part of the design.

**Status:** contract implemented in Phase 0; agent itself ships in Phase 11.

---

## 1. Threats the agent must survive

| Threat                                    | Consequence without a control                 |
| ----------------------------------------- | ---------------------------------------------- |
| Attacker reaches the agent port           | Arbitrary local execution                      |
| Stolen/leaked token                       | Same, from anywhere on the network             |
| Job carrying an unexpected operation      | An operation nobody reviewed                   |
| Path containing `..` or a symlink         | Read/write outside the intended tree           |
| Case or separator tricks (Windows)        | Same, harder to spot                           |
| Endless job                               | Machine unusable                               |
| Job spawns a shell                       | Full control of the PC                         |
| Missing audit record                      | No way to prove what happened                  |

---

## 2. Controls

### 2.1 Authentication
- Shared bearer token (`LOCAL_AGENT_TOKEN`) generated locally, stored in
  `.env`, never committed.
- Token required on **every** request; missing/incorrect ⇒ `401` + audit entry.
- Token comparison is constant-time.
- Disabled by default: `LOCAL_AGENT_ENABLED=false`.

### 2.2 Authorisation
- Each job names an authenticated principal (`requested_by`, non-empty).
- The agent checks that the principal is allowed to submit that operation.

### 2.3 Operation allow-list
- Operations are a closed enum (`JobOperation`), implemented in
  `harsh_quant_os.contracts.jobs`.
- `extra="forbid"` means an unknown operation cannot even be parsed.
- Adding an operation requires a code change and review — never a payload.

### 2.4 Path allow-list
- `allowed_roots` is an explicit tuple; **empty means no access at all**.
- Every target path is canonicalised (resolve `.`/`..`, symlinks, 8.3 short
  names) **before** a prefix comparison.
- The comparison is done on normalised, case-folded Windows paths.
- Any path that escapes its root after canonicalisation ⇒ `403` + job failure.
- The agent refuses to operate on system directories even if configured to.

### 2.5 Job control
- Server-generated UUID job id; clients cannot choose one.
- Status transitions are validated (`queued → running → terminal`).
- Concurrency limit (default 1) and timeout (default 3600 s) enforced.
- Cancellation terminates the job and discards partial output.
- Terminal states are immutable; retries create a new job.

### 2.6 No shell
- There is no code path that builds or executes a command string.
- Operations are reviewed Python functions with typed inputs and outputs.

### 2.7 Resource limits
- Output size caps, temp-directory scoping, and memory/CPU ceilings where the
  platform allows them.

### 2.8 Audit
- Append-only record per job: job id, principal, operation, roots, start/end,
  result, error, duration.
- If the audit write fails, the job does not start (fail closed).
- Audit records are never updated or deleted by application code.

### 2.9 Transport
- Binds `127.0.0.1` by default.
- A token is required even on loopback.
- Exposing the agent beyond localhost is an explicit, documented, reviewed
  decision — never a default.

---

## 3. Adversarial test plan (Phase 11)

`tests/security/` must include:

- missing token, wrong token, expired token ⇒ rejected;
- unknown operation ⇒ rejected;
- `allowed_roots` empty ⇒ rejected;
- `..\\..\\` escape, absolute path outside root, symlink to outside,
  Windows short-name alias, trailing-dot/space name, mixed separators,
  case-variant prefix ⇒ all rejected;
- exceeding concurrency ⇒ queued, not run;
- timeout ⇒ job cancelled with an audit record;
- audit failure ⇒ job never starts;
- cancellation during execution ⇒ clean stop, no partial artefacts.

---

## 4. Operator guidance

- Keep the agent **off** unless you are running local jobs.
- Set `LOCAL_AGENT_ALLOWED_ROOTS` to the narrowest directories you need.
- Regenerate the token if you suspect exposure; rotation steps are in
  [secrets management](secrets-management.md).
- Do not port-forward the agent.
- Review the audit log when a job fails repeatedly.

---

## 5. What the agent is not

- Not a remote administration tool.
- Not a file browser.
- Not a scheduler for arbitrary scripts.
- Not reachable by the browser directly.

See [local agent architecture](../architecture/local-agent.md).
