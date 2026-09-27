# Development Docker configuration

Docker is **optional**. It exists to provide a reproducible PostgreSQL for
local development. Nothing in Phase 0 requires it, and the health check
reports its absence honestly rather than failing.

## Services

| Service  | Image             | Port | Enabled by default | Purpose                    |
| -------- | ----------------- | ---- | ------------------ | -------------------------- |
| postgres | `postgres:16-alpine` | 5432 | Yes            | Development database       |
| redis    | `redis:7-alpine`  | 6379 | No (`--profile redis`) | Optional queue/cache (Phase 1) |

Both are bound to localhost and joined to an internal bridge network.

## Commands

```powershell
npm run db:start     # docker compose up -d postgres
npm run db:logs      # docker compose logs -f postgres
npm run db:stop      # docker compose stop postgres
npm run db:reset     # scripts\data\reset-database.ps1 -Force  (development only)
```

Equivalent raw commands:

```powershell
docker compose up -d postgres
docker compose --profile redis up -d redis
docker compose ps
docker compose down            # stops; keeps the volume
docker compose down -v         # stops AND deletes the data volume
```

## Migrations

No migrations exist yet — Phase 2 introduces Alembic. Until then the database
is created empty by the container, and `scripts/data/setup-database.ps1`
reports that fact instead of pretending to have migrated anything.

## Resetting

`scripts\data\reset-database.ps1` refuses to run unless:

- `APP_ENV` is `development` in `.env`;
- `DATABASE_HOST` is a loopback address;
- `-Force` is passed.

It drops and recreates the `public` schema inside the local container only.

## Configuration

Values come from `.env` (see `.env.example`):

```text
DATABASE_NAME  harsh_quant_os
DATABASE_USER  harsh_quant_os
DATABASE_PORT  5432
```

The container and the API share one credential: `POSTGRES_PASSWORD` inside the
compose file reads `DATABASE_PASSWORD` from `.env`, so both sides always agree.
`docker compose up` aborts with a clear message if that key is missing or still
holds a template placeholder. Generate it locally with:

```powershell
npm run env:provision   # scripts\setup\provision-env.ps1
```

Ports bind to `127.0.0.1` only, so neither service is reachable from the LAN.

## Tests

Docker-dependent paths are not exercised on machines without Docker. The
health check reports `WARN` for Docker, and `setup-database.ps1` prints the
exact manual steps in that case. Nothing here claims success it did not
observe.
