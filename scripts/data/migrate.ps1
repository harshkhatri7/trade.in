<#
.SYNOPSIS
    HARSH QUANT OS - apply database migrations.

.DESCRIPTION
    Runs `alembic upgrade head` (or `alembic downgrade <revision>`) against
    the database alembic itself will use - `HQOS_DATABASE_URL` when it is set,
    otherwise `DATABASE_URL` from .env - then reads the revision the database
    actually reports afterwards.

    Every message describes something that was observed. If alembic exits
    non-zero, or no revision is recorded afterwards, this script prints the
    failure and exits non-zero - it never reports success it did not see.

    Alembic runs through Start-Process with its streams redirected to files.
    Capturing a native command's stderr by piping it instead makes PowerShell
    turn every line into an ErrorRecord, rendered as a NativeCommandError
    block that buries alembic's own words under formatting. The file handles
    keep Python's text exactly as Python wrote it, and what is shown is
    redacted - an error line must never be a place a password escapes.

.PARAMETER Downgrade
    Reverse migrations instead of applying them. Destructive: this drops the
    application tables and the data in them.

.PARAMETER Revision
    Target revision for -Downgrade. Defaults to `base`.
#>
[CmdletBinding()]
param(
    [switch]$Downgrade,
    [string]$Revision = 'base'
)

function Remove-Credential {
    param([string]$Text)
    if (-not $Text) { return '' }
    # Strips `scheme://anything@` so a connection string can be printed
    # without the password that rides along inside it.
    return [regex]::Replace($Text, '://[^@\s]*@', '://<redacted>@')
}

function Format-Failure {
    param([string]$Text)
    if (-not $Text) { return '' }
    # The root cause of a Python traceback is its last line; sixty frames of
    # library code above it bury the one line an operator needs.
    $lines = $Text -split "`r?`n" | Where-Object { $_.Trim() -ne '' }
    $tail = $lines | Select-Object -Last 10
    return Remove-Credential (($tail | ForEach-Object { $_ }) -join [Environment]::NewLine)
}

function Invoke-Alembic {
    <#
      Runs one alembic command and returns its exit code, stdout and stderr
      as plain text. The two streams are kept apart: alembic writes its log
      to stderr and its results to stdout, so the recorded revision arrives
      on stdout while progress (or a traceback) arrives on stderr.
    #>
    param([string[]]$AlembicArguments)

    # Start-Process rather than `&`: capturing a native command's streams by
    # redirection still makes PowerShell turn each stderr line into an
    # ErrorRecord (rendered as a NativeCommandError block on the console),
    # which buries alembic's own words under formatting. The child's file
    # handles are used directly here, so the text is exactly as Python wrote
    # it - and therefore safe to redact and print.
    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()
    $argumentLine = (('-m', 'alembic') + $AlembicArguments | ForEach-Object { '"{0}"' -f $_ }) -join ' '
    try {
        $process = Start-Process -FilePath $venvPython `
            -ArgumentList $argumentLine `
            -WorkingDirectory $repoRoot `
            -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $outFile `
            -RedirectStandardError $errFile
        $code = $process.ExitCode
        $out = Get-Content $outFile -Raw
        $text = Get-Content $errFile -Raw
    }
    finally {
        Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }

    return [pscustomobject]@{
        ExitCode = $code
        StdOut   = if ($out) { [string]$out } else { '' }
        StdErr   = if ($text) { [string]$text } else { '' }
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host 'FAIL  .venv missing - run scripts\setup\setup.ps1' -ForegroundColor Red
    exit 1
}

Push-Location $repoRoot
try {
    Write-Host ''
    Write-Host 'HARSH QUANT OS - database migrations (development only)' -ForegroundColor Cyan

    # alembic/env.py prefers HQOS_DATABASE_URL over .env, so the target named
    # here has to come from the same place - otherwise the script could report
    # one database while migrating another.
    $targetUrl = [string]$env:HQOS_DATABASE_URL
    $targetSource = 'HQOS_DATABASE_URL'
    if (-not $targetUrl) {
        $targetSource = '.env'
        $envFile = Join-Path $repoRoot '.env'
        if (-not (Test-Path $envFile)) {
            Write-Host '  FAIL  .env not found - run npm run env:provision first' -ForegroundColor Red
            exit 1
        }

        Get-Content $envFile | ForEach-Object {
            $line = $_.Trim()
            if (-not $targetUrl -and $line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
                $pair = $line.Split('=', 2)
                if ($pair[0].Trim() -ieq 'DATABASE_URL') { $targetUrl = $pair[1].Trim() }
            }
        }
    }
    if (-not $targetUrl) {
        Write-Host '  FAIL  DATABASE_URL is not set in .env' -ForegroundColor Red
        exit 1
    }
    if ($targetUrl -like '*replace-with*') {
        Write-Host '  FAIL  DATABASE_URL still holds a placeholder - run npm run env:provision' -ForegroundColor Red
        exit 1
    }

    # The target is reported; the connection string is not, because it
    # carries the password.
    Write-Host ('  target (' + $targetSource + '): ' + (Remove-Credential $targetUrl)) -ForegroundColor DarkGray

    if ($Downgrade) {
        Write-Host "  WARNING  downgrade to $Revision drops the application tables and their data" -ForegroundColor Yellow
        $arguments = @('downgrade', $Revision)
        $expectRevision = $false
    }
    else {
        $arguments = @('upgrade', 'head')
        $expectRevision = $true
    }

    Write-Host ('  alembic ' + ($arguments -join ' ') + ' ...') -ForegroundColor Cyan
    $run = Invoke-Alembic $arguments
    if ($run.ExitCode -ne 0) {
        Write-Host "  FAIL  alembic exited with code $($run.ExitCode)" -ForegroundColor Red
        Write-Host (Format-Failure $run.StdErr) -ForegroundColor Red
        exit 1
    }
    if ($run.StdErr.Trim() -ne '') {
        Write-Host (Remove-Credential $run.StdErr.Trim()) -ForegroundColor DarkGray
    }

    # Ask the database which revision it holds, rather than assuming the run
    # above left it where it was supposed to.
    $ask = Invoke-Alembic @('current')
    if ($ask.ExitCode -ne 0) {
        Write-Host '  FAIL  could not read the current revision' -ForegroundColor Red
        Write-Host (Format-Failure $ask.StdErr) -ForegroundColor Red
        exit 1
    }

    # `current` writes the revision to stdout and its log to stderr, so the
    # revision is the only line left here. Last non-empty is a safety net in
    # case a future alembic version adds a banner.
    $recorded = (
        $ask.StdOut -split "`r?`n" |
        Where-Object { $_.Trim() -ne '' } |
        Select-Object -Last 1
    )
    if ($null -eq $recorded) { $recorded = '' }
    $recorded = $recorded.Trim()

    if ($expectRevision) {
        if ($recorded -eq '') {
            Write-Host '  FAIL  no revision recorded after upgrade' -ForegroundColor Red
            exit 1
        }
        Write-Host "  ok    current revision: $recorded" -ForegroundColor Green
    }
    else {
        if ($recorded -eq '') {
            Write-Host '  ok    no revision recorded, as a downgrade to base requires' -ForegroundColor Green
        }
        else {
            Write-Host "  FAIL  a revision is still recorded: $recorded" -ForegroundColor Red
            exit 1
        }
    }
    exit 0
}
finally {
    Pop-Location
}
