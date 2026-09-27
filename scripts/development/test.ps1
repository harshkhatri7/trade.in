<#
.SYNOPSIS
    HARSH QUANT OS - run the test suites.
.DESCRIPTION
    Runs pytest and Vitest and reports the real exit codes.
    Exit code 0 only if both passed.
#>
[CmdletBinding()]
param(
    [switch]$PythonOnly,
    [switch]$TypeScriptOnly,
    [string]$Filter = ''
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Push-Location $repoRoot
try {
    $failed = @()
    $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'

    if (-not $TypeScriptOnly) {
        if (Test-Path $venvPython) {
            Write-Host 'pytest' -ForegroundColor Cyan
            if ($Filter) { & $venvPython -m pytest -q -k $Filter }
            else { & $venvPython -m pytest -q }
            if ($LASTEXITCODE -ne 0) { $failed += 'pytest' }
        } else {
            Write-Host 'FAIL  .venv missing - run scripts\setup\setup.ps1' -ForegroundColor Red
            $failed += '.venv'
        }
    }

    if (-not $PythonOnly) {
        Write-Host 'vitest' -ForegroundColor Cyan
        if ($Filter) { & npx.cmd vitest run $Filter }
        else { & npx.cmd vitest run }
        if ($LASTEXITCODE -ne 0) { $failed += 'vitest' }
    }

    Write-Host ''
    if ($failed.Count -eq 0) {
        Write-Host 'All requested test suites passed.' -ForegroundColor Green
        exit 0
    }
    Write-Host ('Failed: ' + ($failed -join ', ')) -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
