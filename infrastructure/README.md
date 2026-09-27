# Infrastructure

| Directory    | Contents                                                     |
| ------------ | ------------------------------------------------------------ |
| `docker/`    | Development container configuration and usage notes          |
| `database/`  | Bootstrap SQL and, from Phase 2, migration support           |
| `deployment/`| Deployment definitions (Phase 1+) — empty until then         |
| `monitoring/`| Monitoring and alerting configuration (Phase 12+) — empty    |

See [infrastructure/docker/README.md](docker/README.md) for how to start,
stop, inspect and reset the local PostgreSQL service.

Docker is optional at Phase 0. Without it, database-related scripts report
exactly what they could not do.
