<#
.SYNOPSIS
    HARSH QUANT OS - format both languages in place.
.DESCRIPTION
    Runs Prettier and Ruff format. Only source and configuration files are
    touched; data, notebooks and generated output are never rewritten.
#>
[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$PythonOnly,
    [switch]$TypeScriptOnly
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Push-Location $repoRoot
try {
    $failed = @()
    $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'

    if (-not $TypeScriptOnly) {
        if ($CheckOnly) {
            Write-Host 'prettier --check' -ForegroundColor Cyan
            & npx.cmd prettier --check .
        } else {
            Write-Host 'prettier --write' -ForegroundColor Cyan
            & npx.cmd prettier --write .
        }
        if ($LASTEXITCODE -ne 0) { $failed += 'prettier' }
    }

    if (-not $PythonOnly) {
        if (-not (Test-Path $venvPython)) {
            Write-Host 'FAIL  .venv missing' -ForegroundColor Red
            $failed += '.venv'
        } else {
            if ($CheckOnly) {
                Write-Host 'ruff format --check' -ForegroundColor Cyan
                & $venvPython -m ruff format --check .
            } else {
                Write-Host 'ruff format' -ForegroundColor Cyan
                & $venvPython -m ruff format .
            }
            if ($LASTEXITCODE -ne 0) { $failed += 'ruff format' }
        }
    }

    Write-Host ''
    if ($failed.Count -eq 0) {
        if ($CheckOnly) { Write-Host 'Formatting is clean.' -ForegroundColor Green }
        else { Write-Host 'Formatting applied.' -ForegroundColor Green }
        exit 0
    }
    Write-Host ('Formatting problems: ' + ($failed -join ', ')) -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
