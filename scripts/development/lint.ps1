<#
.SYNOPSIS
    HARSH QUANT OS - lint both languages.
.DESCRIPTION
    Runs Ruff, ESLint and the type checkers. Reports real exit codes.
#>
[CmdletBinding()]
param(
    [switch]$Fix,
    [switch]$PythonOnly,
    [switch]$TypeScriptOnly
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Push-Location $repoRoot
try {
    $failed = @()
    $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'

    if (-not $TypeScriptOnly) {
        if (-not (Test-Path $venvPython)) {
            Write-Host 'FAIL  .venv missing' -ForegroundColor Red
            $failed += '.venv'
        } else {
            Write-Host 'ruff check' -ForegroundColor Cyan
            if ($Fix) { & $venvPython -m ruff check --fix . }
            else { & $venvPython -m ruff check . }
            if ($LASTEXITCODE -ne 0) { $failed += 'ruff' }

            Write-Host 'ruff format' -ForegroundColor Cyan
            if ($Fix) { & $venvPython -m ruff format . }
            else { & $venvPython -m ruff format --check . }
            if ($LASTEXITCODE -ne 0) { $failed += 'ruff format' }

            Write-Host 'mypy' -ForegroundColor Cyan
            & $venvPython -m mypy
            if ($LASTEXITCODE -ne 0) { $failed += 'mypy' }
        }
    }

    if (-not $PythonOnly) {
        Write-Host 'eslint' -ForegroundColor Cyan
        if ($Fix) { & npx.cmd eslint . --fix }
        else { & npx.cmd eslint . }
        if ($LASTEXITCODE -ne 0) { $failed += 'eslint' }

        Write-Host 'tsc' -ForegroundColor Cyan
        & npx.cmd tsc --noEmit -p tsconfig.json
        if ($LASTEXITCODE -ne 0) { $failed += 'tsc' }
    }

    Write-Host ''
    if ($failed.Count -eq 0) {
        Write-Host 'Lint passed.' -ForegroundColor Green
        exit 0
    }
    Write-Host ('Lint failed: ' + ($failed -join ', ')) -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
