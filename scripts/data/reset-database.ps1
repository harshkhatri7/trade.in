<#
.SYNOPSIS
    HARSH QUANT OS - reset the LOCAL DEVELOPMENT database.

.DESCRIPTION
    DESTRUCTIVE. Drops and recreates the development PostgreSQL database.

    Safety rules enforced by this script:
      * refuses to run unless APP_ENV is 'development' in .env
      * refuses to run without -Force
      * refuses to run against a URL that is not on localhost
      * prints exactly what it will destroy before doing anything

    Nothing is deleted from the filesystem. No data outside PostgreSQL is
    touched.
#>
[CmdletBinding()]
param(
    [switch]$Force
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Push-Location $repoRoot
try {
    $envFile = Join-Path $repoRoot '.env'
    Write-Host ''
    Write-Host 'HARSH QUANT OS - database reset (destructive)' -ForegroundColor Yellow

    if (-not (Test-Path $envFile)) {
        Write-Host '  FAIL  .env not found - cannot confirm the environment.' -ForegroundColor Red
        exit 1
    }

    $vars = @{}
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
            $k, $v = $line.Split('=', 2)
            $vars[$k.Trim()] = $v.Trim()
        }
    }

    $appEnv = $vars['APP_ENV']
    if ($appEnv -ne 'development') {
        Write-Host ("  REFUSED  APP_ENV is '" + $appEnv + "' - this script only runs in 'development'.") -ForegroundColor Red
        exit 1
    }

    $dbHost = $vars['DATABASE_HOST']
    if ($dbHost -notin @('127.0.0.1', 'localhost', '::1')) {
        Write-Host ("  REFUSED  DATABASE_HOST is '" + $dbHost + "' - refusing to reset a non-local database.") -ForegroundColor Red
        exit 1
    }

    $dbName = $vars['DATABASE_NAME']
    if (-not $dbName) { $dbName = 'harsh_quant_os' }

    Write-Host ("  target   " + $dbHost + ':' + $vars['DATABASE_PORT'] + '/' + $dbName) -ForegroundColor White
    Write-Host '  action   DROP SCHEMA public CASCADE, then recreate it' -ForegroundColor White

    if (-not $Force) {
        Write-Host ''
        Write-Host '  This is destructive. Re-run with -Force to proceed.' -ForegroundColor Yellow
        exit 1
    }

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host '  FAIL  Docker is not installed - cannot reach the local PostgreSQL container.' -ForegroundColor Red
        exit 1
    }

    $psqlUser = $vars['DATABASE_USER']
    if (-not $psqlUser) { $psqlUser = 'harsh_quant_os' }

    Write-Host '  resetting...' -ForegroundColor Cyan
    & docker compose exec -T postgres psql -U $psqlUser -d $dbName -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
    if ($LASTEXITCODE -ne 0) {
        Write-Host '  FAIL  reset did not complete - check the output above.' -ForegroundColor Red
        exit 1
    }

    Write-Host '  ok    schema recreated' -ForegroundColor Green
    Write-Host '  info  no migrations exist yet (Phase 2) - the database is intentionally empty' -ForegroundColor DarkGray
    exit 0
}
finally {
    Pop-Location
}
