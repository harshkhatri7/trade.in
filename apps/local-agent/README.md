# apps/local-agent — Local compute bridge (Phase 11)

The only component with access to the researcher's PC.

**Status: not implemented.** The job contract it will speak already exists and
is tested:

- `harsh_quant_os.contracts.jobs.LocalAgentJob`
- `harsh_quant_os.contracts.jobs.JobOperation` (closed allow-list)
- `harsh_quant_os.contracts.jobs.JobStatus`
- TypeScript mirror in `@harsh-quant-os/types` with a parity test

Planned behaviour:

```text
API ──(token + job)──► agent ──(operation allow-list)──► reviewed function
                            ──(path allow-list)───────► local filesystem
                            ──(timeout, concurrency)──► bounded resources
                            ──(append-only audit)─────► record
```

Non-negotiable: no shell, no arbitrary paths, no unauthenticated access,
fail-closed when auditing is unavailable, disabled by default.

See [docs/architecture/local-agent.md](../../docs/architecture/local-agent.md)
and [docs/security/local-agent-security.md](../../docs/security/local-agent-security.md).
