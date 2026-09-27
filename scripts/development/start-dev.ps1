<#
.SYNOPSIS
    HARSH QUANT OS - start the development services that exist.

.DESCRIPTION
    Phase 0 has no runnable application services, and this script says so
    instead of pretending to start something.

    As phases land, this script will start the API, the web app and
    (optionally) PostgreSQL. Each service is only started if its code exists.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\development\start-dev.ps1
#>
[CmdletBinding()]
param(
    [switch]$WithDatabase,
    [switch]$WithWeb,
    [switch]$WithApi
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Push-Location $repoRoot
try {
    Write-Host ''
    Write-Host 'HARSH QUANT OS - development startup' -ForegroundColor Cyan

    $started = @()
    $skipped = @()

    # ---------------- PostgreSQL ----------------
    if ($WithDatabase) {
        if (Get-Command docker -ErrorAction SilentlyContinue) {
            & docker compose up -d postgres 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { $started += 'postgres (docker compose)' }
            else { Write-Host '  FAIL  could not start postgres' -ForegroundColor Red; exit 1 }
        } else {
            $skipped += 'postgres - Docker is not installed'
        }
    } else {
        $skipped += 'postgres - not requested (-WithDatabase)'
    }

    # ---------------- API ----------------
    if ($WithApi) {
        $entry = Join-Path $repoRoot 'apps\api'
        $hasApp = (Test-Path (Join-Path $entry 'main.py')) -or (Test-Path (Join-Path $entry 'app.py'))
        if ($hasApp) {
            Write-Host '  starting API on http://127.0.0.1:8000 ...' -ForegroundColor Green
            $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
            & $venvPython -m uvicorn --app-dir $entry 'main:app' --reload
            $started += 'api'
        } else {
            $skipped += 'api - apps/api/main.py does not exist yet (Phase 1)'
        }
    } else {
        $skipped += 'api - not requested (-WithApi)'
    }

    # ---------------- Web ----------------
    if ($WithWeb) {
        $webPkg = Join-Path $repoRoot 'apps\web\package.json'
        if (Test-Path $webPkg) {
            Write-Host '  starting web on http://127.0.0.1:3000 ...' -ForegroundColor Green
            & npm.cmd run dev --workspace apps/web
            $started += 'web'
        } else {
            $skipped += 'web - apps/web/package.json does not exist yet (Phase 1)'
        }
    } else {
        $skipped += 'web - not requested (-WithWeb)'
    }

    Write-Host ''
    if ($started.Count -eq 0) {
        Write-Host 'Nothing was started.' -ForegroundColor Yellow
        Write-Host 'This repository is in Phase 0 (Foundation): there are no application' -ForegroundColor Yellow
        Write-Host 'services yet. Use the health check and validation gate instead:' -ForegroundColor Yellow
        Write-Host '  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\development\health-check.ps1'
        Write-Host '  npm run check'
        Write-Host ''
        Write-Host 'Skipped:' -ForegroundColor DarkGray
        foreach ($item in $skipped) { Write-Host ('  - ' + $item) -ForegroundColor DarkGray }
        exit 0
    }

    Write-Host 'Started:' -ForegroundColor Green
    foreach ($item in $started) { Write-Host ('  - ' + $item) }
    if ($skipped.Count -gt 0) {
        Write-Host 'Skipped:' -ForegroundColor DarkGray
        foreach ($item in $skipped) { Write-Host ('  - ' + $item) -ForegroundColor DarkGray }
    }
    exit 0
}
finally {
    Pop-Location
}
