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

    Ports are printed after startup. Stop everything with Ctrl+C: shutdown is
    verified against the started ports before the script reports success, so
    an orphaned reload worker cannot be mistaken for a stopped API.

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
$webUrlToPrint = 'http://' + $webHost + ':' + $webPort

if ($startWeb) {
    $allowedOrigins = @((Get-ConfigValue 'API_ALLOWED_ORIGINS' '') -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
    $boundOrigin = $webUrlToPrint

    if ($allowedOrigins -notcontains $boundOrigin) {
        # Never hand over a URL the API will refuse: that page can only ever
        # report DISCONNECTED, however healthy the API is. Prefer an origin
        # from the allow-list that listens on the same port, and say plainly
        # what has to change in .env to use the 127.0.0.1 form.
        $usable = @($allowedOrigins | Where-Object { $_ -like ('http://*:' + $webPort) })
        $usableOrigin = $null
        if ($usable.Count -gt 0) { $usableOrigin = $usable[0] }
        if ($usableOrigin) { $webUrlToPrint = $usableOrigin }

        Write-Host ''
        Write-Host ('  WARN  ' + $boundOrigin + ' is not in API_ALLOWED_ORIGINS') -ForegroundColor Yellow
        if ($usableOrigin) {
            Write-Host ('        Printing ' + $webUrlToPrint + ' instead: that origin is allowed, so the page') -ForegroundColor Yellow
            Write-Host '        can reach the API. To use the 127.0.0.1 address, add this line to .env:' -ForegroundColor Yellow
        } else {
            Write-Host '        Nothing in the list listens on port ' + $webPort + ', so the page will show' -ForegroundColor Yellow
            Write-Host '        DISCONNECTED. Add this line to .env:' -ForegroundColor Yellow
        }
        $suggestedOrigins = @($allowedOrigins) + $boundOrigin
        Write-Host ('        API_ALLOWED_ORIGINS=' + ($suggestedOrigins -join ',')) -ForegroundColor Yellow
    }
}

# ---------------------------------------------------------------- helpers

$childProcesses = @()
# Parallel to $childProcesses: the name of each service whose process is at
# that index, so a process that dies can be reported as "api" or "web"
# rather than as an anonymous pid.
$serviceNames = @()
$startedPorts = @()
# Set once the normal path has already stopped and checked everything. The
# `finally` safety net must then stay silent: a second pass can observe a
# different world than the first (another instance may have taken the port in
# between) and would print a warning that contradicts the result above it.
$shutdownPerformed = $false
# Set when a service stopped on its own instead of being stopped here. The
# ports can still be released and verified afterwards; the run still has to
# finish non-zero, because a service that died unasked is not a success.
$serviceFailed = $false

# pid -> StartTime for every descendant observed while its service was still
# healthy. The TCP table reports the PID that *created* a listening socket,
# so once a child inherits that socket and the creator exits, the port alone
# can no longer name the process that is really holding it. Recording the
# tree up front means those children can still be reaped later by PID, with
# the start time guarding against a reused PID.
$serviceDescendants = @{}

function Get-ProcessStartTime {
    param([int]$ProcessId)

    try { return (Get-Process -Id $ProcessId -ErrorAction Stop).StartTime }
    catch { return $null }
}

# Every process below the given root (the root itself is not included).
function Get-DescendantPids {
    param([int]$RootId)

    $found = @()
    $queue = @($RootId)
    $index = 0
    $seen = @{}
    while ($index -lt $queue.Count) {
        $current = $queue[$index]
        $index++
        if ($seen.ContainsKey($current)) { continue }
        $seen[$current] = $true
        $children = @(Get-CimInstance Win32_Process -Filter ('ParentProcessId=' + $current) -ErrorAction SilentlyContinue)
        foreach ($child in $children) {
            $found += [int]$child.ProcessId
            $queue += [int]$child.ProcessId
        }
    }
    return $found
}

# Add to the snapshot; never clears it, so descendants captured while the
# service was healthy survive even if the root has since exited.
function Save-ServiceTrees {
    foreach ($proc in @($childProcesses)) {
        if ($null -eq $proc) { continue }
        foreach ($descendant in Get-DescendantPids -RootId $proc.Id) {
            $start = Get-ProcessStartTime -ProcessId $descendant
            if ($null -ne $start) { $serviceDescendants[$descendant] = $start }
        }
    }
}

# Poll until *our own* API process answers its health contract. Two ways a
# poll can be a lie: something else already owns the port (so a reply proves
# nothing), or the process we started has already died while an earlier one
# is still answering. Both are rejected: the process must be alive and the
# reply must be HTTP 200 with a JSON body.
function Wait-ForApiHealth {
    param([string]$Url, $Process, [int]$TimeoutSeconds = 20)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if ($null -ne $Process) {
            try { if ($Process.HasExited) { return $false } } catch { return $false }
        }
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            $contentType = [string]($response.Headers['Content-Type'])
            if ([int]$response.StatusCode -eq 200 -and $contentType -like '*application/json*') { return $true }
        } catch { }
        Start-Sleep -Milliseconds 400
    } while ((Get-Date) -lt $deadline)
    return $false
}

# Does the process listening on $Port belong to the tree we started? The TCP
# table names the PID that *created* the socket, and a stranger can be
# listening on the same port while our own process is still coming up, so an
# HTTP 200 on its own says nothing about the server we just launched. The
# reply counts only when a process in our own tree is the one answering.
function Test-OwnedListener {
    param([int]$Port, $Root)

    if ($null -eq $Root) { return $false }
    try { if ($Root.HasExited) { return $false } } catch { return $false }

    # Hosts without the networking cmdlets cannot be ownership-checked. Say
    # so rather than pretend the check ran: liveness of our own process is
    # still required above, which is the same guarantee the API wait gives.
    if (-not (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue)) { return $true }

    $ownerIds = @()
    foreach ($listener in @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
        $ownerIds += [int]$listener.OwningProcess
    }
    if ($ownerIds.Count -eq 0) { return $false }

    $ours = @([int]$Root.Id) + @(Get-DescendantPids -RootId ([int]$Root.Id))
    foreach ($ownerId in $ownerIds) { if ($ours -contains $ownerId) { return $true } }
    return $false
}

# Poll until *our own* web process serves the page. Same two lies as the API
# wait: a reply from a server we do not own proves nothing, and neither does
# one that arrives after the process we started has died. Both are rejected.
function Wait-ForWebPage {
    param([string]$Url, [int]$Port, $Process, [int]$TimeoutSeconds = 90)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if ($null -ne $Process) {
            try { if ($Process.HasExited) { return $false } } catch { return $false }
        }
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
            if ([int]$response.StatusCode -eq 200 -and (Test-OwnedListener -Port $Port -Root $Process)) {
                return $true
            }
        } catch { }
        Start-Sleep -Milliseconds 400
    } while ((Get-Date) -lt $deadline)
    return $false
}

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

# Stop every service this script started and *check* before saying so.
# Returns a list of problems; an empty list means every port we started was
# observed released. Two facts shape this: `taskkill /T` walks down from the
# given PID, so once a tracked root has already exited it finds nothing; and
# the TCP table reports the PID that *created* a listening socket, which goes
# stale as soon as a child inherits that socket. So the tree is snapshotted
# while the service is healthy and again here while the roots may still be
# alive, and the recorded PIDs are reaped before the ports are checked.
# Anything this script cannot identify is reported, never killed.
function Stop-StartedServices {
    param([int[]]$Ports)

    # Snapshot first: a root that has already exited cannot be walked later.
    Save-ServiceTrees
    foreach ($proc in @($childProcesses)) { Stop-ChildTree -Process $proc }

    $portsToWatch = @($Ports | Where-Object { $_ -gt 0 } | Select-Object -Unique)
    $canCheckPorts = $null -ne (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue)

    function Get-Listeners {
        param([int]$Port)
        @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    }

    # Grace period: let the tree notice the shutdown and exit on its own.
    $graceUntil = (Get-Date).AddSeconds(3)
    while ((Get-Date) -lt $graceUntil) {
        if (-not $canCheckPorts) { break }
        $listening = @()
        foreach ($port in $portsToWatch) { $listening += Get-Listeners -Port $port }
        if ($listening.Count -eq 0) { break }
        Start-Sleep -Milliseconds 300
    }

    # Reap descendants recorded while the service was healthy, re-checked
    # against their recorded start time so a reused PID is never killed.
    foreach ($knownPid in @($serviceDescendants.Keys)) {
        $expectedStart = $serviceDescendants[$knownPid]
        $actualStart = Get-ProcessStartTime -ProcessId $knownPid
        if ($null -ne $actualStart -and $actualStart -eq $expectedStart) {
            & taskkill.exe /PID $knownPid /T /F 2>&1 | Out-Null
        }
    }

    $problems = @()
    if ($portsToWatch.Count -gt 0 -and -not $canCheckPorts) {
        return @('stopped the recorded service tree, but cannot verify port release: Get-NetTCPConnection is unavailable on this host')
    }

    # Inspect what still holds a port we started. Nothing is killed here.
    # A PID is proof of ownership only if it was recorded as this run's own
    # descendant (reaped just above); "same repository path, started later"
    # is not proof at all - another instance of this very script would match
    # it too, and it must never be killed to make one session's shutdown
    # look complete. Anything unrecognised is reported and left running.
    foreach ($port in $portsToWatch) {
        foreach ($listener in Get-Listeners -Port $port) {
            $ownerId = [int]$listener.OwningProcess
            $commandLine = $null
            try {
                $commandLine = (Get-CimInstance Win32_Process -Filter ('ProcessId=' + $ownerId) -ErrorAction Stop).CommandLine
            } catch { $commandLine = $null }

            if ($null -eq $commandLine) {
                $problems += ('port ' + $port + ' is still bound but pid ' + $ownerId + ' no longer exists - a child inherited this socket')
            } elseif ($serviceDescendants.ContainsKey($ownerId)) {
                $problems += ('port ' + $port + ' is still held by a recorded child (pid ' + $ownerId + ') that did not exit')
            } else {
                $problems += ('port ' + $port + ' is held by a process this script did not start (pid ' + $ownerId + ') - left running')
            }
        }
    }

    # Verification: report only what is still observed listening.
    $deadline = (Get-Date).AddSeconds(5)
    do {
        $stillListening = @()
        foreach ($port in $portsToWatch) { $stillListening += Get-Listeners -Port $port }
        if ($stillListening.Count -eq 0) { return $problems }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $deadline)

    foreach ($port in $portsToWatch) {
        foreach ($listener in Get-Listeners -Port $port) {
            $problems += ('port ' + $port + ' is still LISTENING (pid ' + $listener.OwningProcess + ')')
        }
    }
    return $problems
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
            $script:serviceNames += 'api'
            $startedPorts += [int]$apiPort

            # Only report the API as started once it answered a request;
            # a green line that no request ever reached would be a claim,
            # not an observation.
            $healthUrl = 'http://' + $apiHost + ':' + $apiPort + '/api/v1/health'
            if (Wait-ForApiHealth -Url $healthUrl -Process $apiProcess) {
                # Record the process tree now, while it is intact: this is the
                # only moment the reload supervisor's children can be found
                # through their parent, and shutdown needs their PIDs.
                Save-ServiceTrees
                $started += 'api'
                Write-Host ('  API   ' + $healthUrl) -ForegroundColor Green
            } else {
                # No exit code here on purpose: a `-NoNewWindow` child never
                # exposes one in Windows PowerShell, so quoting a number would
                # be quoting a value that was not observed. uvicorn's own
                # error, if any, is already on the console above.
                $detail = 'the API process stayed up but gave no JSON health reply within 20 seconds'
                try {
                    if ($apiProcess.HasExited) { $detail = 'the API process exited before it answered its health contract' }
                } catch { }
                Write-Host ('  FAIL  ' + $detail + ' (' + $healthUrl + ')') -ForegroundColor Red
                exit 1
            }
        } else {
            $skipped += 'api - apps\api\main.py does not exist yet'
        }
    } else {
        $skipped += 'api - not requested'
    }

    # ---------------- Web ----------------
    if ($startWeb) {
        $webPkg = Join-Path $repoRoot 'apps\web\package.json'
        if (Test-Path $webPkg) {
            # One source of truth: the browser is told where the API lives by
            # the same API_BASE_URL the API itself publishes.
            $env:NEXT_PUBLIC_API_BASE_URL = $apiBaseUrl

            # Refuse to start into a port someone else already holds. Making
            # room by killing that process is exactly the kind of damage this
            # script must never do, so it is reported and left running.
            $webListeners = @(Get-NetTCPConnection -LocalPort ([int]$webPort) -State Listen -ErrorAction SilentlyContinue)
            if ($webListeners.Count -gt 0) {
                $holderId = [int]$webListeners[0].OwningProcess
                Write-Host ('  FAIL  port ' + $webPort + ' is already in use (pid ' + $holderId + ') - left running') -ForegroundColor Red
                exit 1
            }

            $npmCmd = Get-Command 'npm.cmd' -ErrorAction SilentlyContinue
            if (-not $npmCmd) {
                Write-Host '  FAIL  npm.cmd was not found (run scripts\setup\setup.ps1)' -ForegroundColor Red
                exit 1
            }

            # Started as a child rather than as a foreground pipeline: only a
            # child can be waited on, observed and reaped. cmd.exe is kept in
            # the chain because that is how npm.cmd runs anyway, and
            # -NoNewWindow keeps the dev-server log on this console.
            $webArgs = '/c ""' + $npmCmd.Source + '" run dev --workspace apps/web -- --hostname ' + $webHost + ' --port ' + $webPort + '"'
            $webProcess = Start-Process -FilePath $env:ComSpec `
                -ArgumentList $webArgs `
                -WorkingDirectory $repoRoot `
                -NoNewWindow -PassThru
            $script:childProcesses += $webProcess
            $script:serviceNames += 'web'
            $startedPorts += [int]$webPort

            # A green line with nothing behind it would be a claim, not an
            # observation: report the web only once the page we would hand
            # over has answered HTTP 200 from our own process tree.
            $webPageUrl = 'http://' + $webHost + ':' + $webPort + '/'
            if (Wait-ForWebPage -Url $webPageUrl -Port ([int]$webPort) -Process $webProcess) {
                # Record the tree while it is intact, as for the API above.
                Save-ServiceTrees
                $started += 'web'
                Write-Host ('  WEB   ' + $webUrlToPrint) -ForegroundColor Green
            } else {
                $detail = 'the web process stayed up but ' + $webPageUrl + ' did not answer HTTP 200 within 90 seconds'
                try {
                    if ($webProcess.HasExited) { $detail = 'the web process exited before it served the page' }
                } catch { }
                Write-Host ('  FAIL  ' + $detail) -ForegroundColor Red
                exit 1
            }
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
    if ($skipped.Count -gt 0) {
        Write-Host 'Skipped:' -ForegroundColor DarkGray
        foreach ($item in $skipped) { Write-Host ('  - ' + $item) -ForegroundColor DarkGray }
    }
    Write-Host ''
    Write-Host 'Press Ctrl+C to stop the services started here.' -ForegroundColor DarkGray
    Write-Host ''

    # Block until Ctrl+C (handled by `finally`) or until a service started
    # here stops on its own. A service dying unasked is not a clean stop: it
    # is named below, the rest are stopped, and the run finishes non-zero so
    # nothing downstream can read it as a success.
    $failedIndex = -1
    while ($failedIndex -lt 0 -and $childProcesses.Count -gt 0) {
        for ($i = 0; $i -lt $childProcesses.Count; $i++) {
            $proc = $childProcesses[$i]
            $hasExited = $false
            try { $hasExited = [bool]$proc.HasExited } catch { $hasExited = $true }
            if ($hasExited) { $failedIndex = $i; break }
        }
        if ($failedIndex -lt 0) { Start-Sleep -Milliseconds 500 }
    }

    if ($failedIndex -ge 0) {
        $failedProc = $childProcesses[$failedIndex]
        $failedName = 'a service'
        if ($failedIndex -lt $serviceNames.Count) { $failedName = $serviceNames[$failedIndex] }

        # A `-NoNewWindow` child never exposes an exit code in Windows
        # PowerShell: the property reads as $null even after the process is
        # observed exited, and [int]$null would print an invented 0. Quote a
        # number only when one was really read - the process's own error, if
        # any, is already on the console above.
        $failedCode = $null
        try { $failedCode = $failedProc.ExitCode } catch { $failedCode = $null }
        $failedDetail = ''
        if ($null -ne $failedCode) { $failedDetail = ' with exit code ' + [int]$failedCode }
        Write-Host ''
        Write-Host ('  FAIL  ' + $failedName + ' stopped unexpectedly' + $failedDetail) -ForegroundColor Red
        $serviceFailed = $true
    }

    Write-Host ''
    $stopProblems = @(Stop-StartedServices -Ports $startedPorts)
    $shutdownPerformed = $true
    if ($stopProblems.Count -eq 0) {
        Write-Host 'All services stopped - every port started here observed released.' -ForegroundColor Cyan
        if ($serviceFailed) { exit 1 }
        exit 0
    }

    Write-Host 'STOP INCOMPLETE - do not assume these services are down:' -ForegroundColor Red
    foreach ($problem in $stopProblems) { Write-Host ('  - ' + $problem) -ForegroundColor Red }
    exit 1
}
finally {
    # Safety net for abnormal exits only (Ctrl+C, an error above). The normal
    # path has already stopped and checked; running again here could only
    # contradict the message it just printed.
    if (-not $shutdownPerformed) {
        $pendingProblems = @(Stop-StartedServices -Ports $startedPorts)
        if ($pendingProblems.Count -gt 0) {
            Write-Host ''
            Write-Host 'WARNING: some services did not stop:' -ForegroundColor Red
            foreach ($problem in $pendingProblems) { Write-Host ('  - ' + $problem) -ForegroundColor Red }
        }
    }
    Pop-Location
}
