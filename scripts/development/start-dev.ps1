<#
.SYNOPSIS
    HARSH QUANT OS - start the development services that exist.

.DESCRIPTION
    Phase 1 has two runnable services: the FastAPI API and the Next.js web
    app. Host and port are read from the repository `.env` file and fall back
    to the same defaults as `.env.example`, so configuration has one source.

    With no switch both services are started. `-WithApi` or `-WithWeb` starts
    only that service. `-WithDatabase` additionally starts PostgreSQL when
    Docker is installed and reports honestly when it is not.

    Ports are printed after startup. Stop everything with Ctrl+C.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\development\start-dev.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\development\start-dev.ps1 -WithApi

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\development\start-dev.ps1 -WithWeb
#>
[CmdletBinding()]
param(
    [switch]$WithDatabase,
    [switch]$WithWeb,
    [switch]$WithApi
)

$ErrorActionPreference = 'Continue'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')

# ---------------------------------------------------------------- configuration

function Read-DotEnvFile {
    param([string]$Path)

    $values = @{}
    if (-not (Test-Path $Path)) { return $values }

    foreach ($line in Get-Content -Path $Path) {
        $trimmed = $line.Trim()
        if ($trimmed -eq '' -or $trimmed.StartsWith('#')) { continue }
        $separator = $trimmed.IndexOf('=')
        if ($separator -lt 1) { continue }

        $key = $trimmed.Substring(0, $separator).Trim()
        $value = $trimmed.Substring($separator + 1).Trim()
        if ($value.Length -ge 2 -and ($value[0] -eq '"' -or $value[0] -eq "'")) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = $value
    }
    return $values
}

$dotEnv = Read-DotEnvFile -Path (Join-Path $repoRoot '.env')

function Get-ConfigValue {
    param([string]$Key, [string]$Default)
    if ($dotEnv.ContainsKey($Key) -and $dotEnv[$Key] -ne '') { return $dotEnv[$Key] }
    return $Default
}

$apiHost  = Get-ConfigValue 'API_HOST' '127.0.0.1'
$apiPort  = Get-ConfigValue 'API_PORT' '8000'
$webHost  = Get-ConfigValue 'WEB_HOST' '127.0.0.1'
$webPort  = Get-ConfigValue 'WEB_PORT' '3000'
$appEnv   = Get-ConfigValue 'APP_ENV' 'development'
$logLevel = Get-ConfigValue 'LOG_LEVEL' 'INFO'
$apiBaseUrl = Get-ConfigValue 'API_BASE_URL' ('http://' + $apiHost + ':' + $apiPort)

# No switch means "start everything that exists". A switch narrows the run to
# the requested service only.
$serviceFilterApplied = ($WithApi -or $WithWeb)
$startApi = (-not $serviceFilterApplied) -or $WithApi
$startWeb = (-not $serviceFilterApplied) -or $WithWeb

# The API answers browser requests only for origins listed in
# API_ALLOWED_ORIGINS. The URL printed below must itself be in that list,
# otherwise the page loads and then honestly reports DISCONNECTED while the
# API sits healthy next to it. Say so here instead of leaving anyone to work
# that out from the screen.
if ($startWeb) {
    $allowedOrigins = @((Get-ConfigValue 'API_ALLOWED_ORIGINS' '') -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
    $printedOrigin = 'http://' + $webHost + ':' + $webPort
    if ($allowedOrigins -notcontains $printedOrigin) {
        $fallbackOrigin = 'http://localhost:' + $webPort
        Write-Host ''
        Write-Host ('  WARN  ' + $printedOrigin + ' is not in API_ALLOWED_ORIGINS') -ForegroundColor Yellow
        Write-Host '        The API is healthy, but the browser will refuse its reply and the' -ForegroundColor Yellow
        Write-Host '        panel will show DISCONNECTED. Either open the page on an origin the' -ForegroundColor Yellow
        if ($allowedOrigins -contains $fallbackOrigin) {
            Write-Host ('        API allows (' + $fallbackOrigin + ') or add this line to .env:') -ForegroundColor Yellow
        } else {
            Write-Host '        API allows no origin from this list. Add this to .env:' -ForegroundColor Yellow
        }
        $suggestedOrigins = @($allowedOrigins) + $printedOrigin
        Write-Host ('        API_ALLOWED_ORIGINS=' + ($suggestedOrigins -join ',')) -ForegroundColor Yellow
    }
}

# ---------------------------------------------------------------- helpers

$childProcesses = @()

function Stop-ChildTree {
    param($Process)

    if ($null -eq $Process) { return }
    try {
        if ($Process.HasExited) { return }
    } catch { return }

    $isWindowsHost = ($env:OS -eq 'Windows_NT')
    if ($isWindowsHost) {
        & taskkill.exe /PID $Process.Id /T /F 2>&1 | Out-Null
    } else {
        try { $Process.Kill() } catch { }
    }
}

Push-Location $repoRoot
try {
    Write-Host ''
    Write-Host 'HARSH QUANT OS - development startup' -ForegroundColor Cyan
    Write-Host ('  environment : ' + $appEnv)
    Write-Host ('  log level   : ' + $logLevel)
    Write-Host ''

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
    if ($startApi) {
        $apiDir = Join-Path $repoRoot 'apps\api'
        $entry = Join-Path $apiDir 'main.py'
        if (Test-Path $entry) {
            $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
            if (Test-Path $venvPython) { $python = $venvPython }
            elseif (Get-Command python -ErrorAction SilentlyContinue) { $python = 'python' }
            else {
                Write-Host '  FAIL  no Python interpreter found (run scripts\setup\setup.ps1)' -ForegroundColor Red
                exit 1
            }

            # Start-Process joins an argument array with plain spaces, which
            # breaks paths containing a space (this repository lives in
            # "Quant os"). One pre-quoted string avoids that.
            $uvicornArgs = '-m uvicorn --app-dir "' + $apiDir + '" main:app --host ' + $apiHost + ' --port ' + $apiPort
            if ($appEnv -ne 'production') { $uvicornArgs += ' --reload' }

            # Settings reads `.env`, so the working directory must be the
            # repository root for both the API and its reload supervisor.
            $apiProcess = Start-Process -FilePath $python `
                -ArgumentList $uvicornArgs `
                -WorkingDirectory $repoRoot `
                -NoNewWindow -PassThru
            $script:childProcesses += $apiProcess
            $started += 'api'
            Write-Host ('  API   http://' + $apiHost + ':' + $apiPort + '/api/v1/health') -ForegroundColor Green
        } else {
            $skipped += 'api - apps\api\main.py does not exist yet'
        }
    } else {
        $skipped += 'api - not requested'
    }

    # ---------------- Web ----------------
    $webRequestedInForeground = $false
    if ($startWeb) {
        $webPkg = Join-Path $repoRoot 'apps\web\package.json'
        if (Test-Path $webPkg) {
            # One source of truth: the browser is told where the API lives by
            # the same API_BASE_URL the API itself publishes.
            $env:NEXT_PUBLIC_API_BASE_URL = $apiBaseUrl
            $started += 'web'
            $webRequestedInForeground = $true
        } else {
            $skipped += 'web - apps\web\package.json does not exist yet'
        }
    } else {
        $skipped += 'web - not requested'
    }

    Write-Host ''
    if ($started.Count -eq 0) {
        Write-Host 'Nothing was started.' -ForegroundColor Yellow
        Write-Host 'Skipped:' -ForegroundColor DarkGray
        foreach ($item in $skipped) { Write-Host ('  - ' + $item) -ForegroundColor DarkGray }
        exit 0
    }

    Write-Host 'Started:' -ForegroundColor Green
    foreach ($item in $started) { Write-Host ('  - ' + $item) }
    if ($webRequestedInForeground) {
        Write-Host ('  WEB   http://' + $webHost + ':' + $webPort) -ForegroundColor Green
    }
    if ($skipped.Count -gt 0) {
        Write-Host 'Skipped:' -ForegroundColor DarkGray
        foreach ($item in $skipped) { Write-Host ('  - ' + $item) -ForegroundColor DarkGray }
    }
    Write-Host ''
    Write-Host 'Press Ctrl+C to stop the services started here.' -ForegroundColor DarkGray
    Write-Host ''

    if ($webRequestedInForeground) {
        # The web app runs in the foreground so its logs and Ctrl+C behave the
        # way a developer expects; the API (if started) is stopped by the
        # `finally` block below.
        & npm.cmd run dev --workspace apps/web -- --hostname $webHost --port $webPort
        if ($LASTEXITCODE -ne 0) {
            Write-Host ('  FAIL  web exited with code ' + $LASTEXITCODE) -ForegroundColor Red
        }
    } elseif ($childProcesses.Count -gt 0) {
        # Only background services: block until they stop.
        foreach ($proc in $childProcesses) {
            try { Wait-Process -Id $proc.Id -ErrorAction SilentlyContinue } catch { }
        }
    }

    Write-Host 'All services stopped.' -ForegroundColor Cyan
    exit 0
}
finally {
    foreach ($proc in $childProcesses) { Stop-ChildTree -Process $proc }
    Pop-Location
}
