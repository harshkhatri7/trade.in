<#
.SYNOPSIS
    HARSH QUANT OS - prepare the local development database.

.DESCRIPTION
    Creates the development PostgreSQL container (or uses an existing server)
    and provisions the development database and role.

    Requires Docker, or a reachable PostgreSQL server. If neither is available
    the script reports exactly what is missing - it never reports success it
    did not observe.

    No migrations exist yet (Phase 2); this script only prepares the empty
    database.
#>
[CmdletBinding()]
param(
    [switch]$UseDocker
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Push-Location $repoRoot
try {
    Write-Host ''
    Write-Host 'HARSH QUANT OS - database setup (development only)' -ForegroundColor Cyan

    $envFile = Join-Path $repoRoot '.env'
    if (-not (Test-Path $envFile)) {
        Write-Host '  FAIL  .env not found - run scripts\setup\setup.ps1 first' -ForegroundColor Red
        exit 1
    }
    $envVars = @{}
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
            $k, $v = $line.Split('=', 2)
            $envVars[$k.Trim()] = $v.Trim()
        }
    }

    if ($envVars['DATABASE_URL'] -like '*replace-with*') {
        Write-Host '  WARN  DATABASE_PASSWORD still holds a placeholder - set a real local password in .env' -ForegroundColor Yellow
    }

    $hasDocker = [bool](Get-Command docker -ErrorAction SilentlyContinue)
    if ($UseDocker -or -not $hasDocker) {
        if (-not $hasDocker) {
            Write-Host '  FAIL  Docker is not installed, and no PostgreSQL server was confirmed.' -ForegroundColor Red
            Write-Host ''
            Write-Host 'Options:' -ForegroundColor Yellow
            Write-Host '  1. Install Docker Desktop, then re-run this script with -UseDocker'
            Write-Host '  2. Install PostgreSQL 16+ yourself and set DATABASE_* in .env'
            Write-Host '  3. Skip: nothing in Phase 0 needs a database.'
            exit 1
        }
        Write-Host '  starting postgres container...' -ForegroundColor Cyan
        & docker compose up -d postgres
        if ($LASTEXITCODE -ne 0) {
            Write-Host '  FAIL  docker compose up failed' -ForegroundColor Red
            exit 1
        }
        Write-Host '  ok    postgres container started' -ForegroundColor Green
        Write-Host '  info  migrations are not implemented yet (Phase 2) - database is empty by design' -ForegroundColor DarkGray
        exit 0
    }

    Write-Host '  info  Docker not available; assuming an external PostgreSQL server.' -ForegroundColor DarkGray
    Write-Host ('  info  target: ' + $envVars['DATABASE_HOST'] + ':' + $envVars['DATABASE_PORT'] + '/' + $envVars['DATABASE_NAME']) -ForegroundColor DarkGray
    Write-Host '  WARN  connectivity was not verified - install Docker or confirm the server manually.' -ForegroundColor Yellow
    exit 0
}
finally {
    Pop-Location
}
