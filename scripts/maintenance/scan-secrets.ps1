<#
.SYNOPSIS
    HARSH QUANT OS - repository secret scan.

.DESCRIPTION
    Runs the dependency-free Python secret scanner plus a few Windows-side
    checks. Reports the number of findings and exits non-zero if any exist.

    Template files (*.example) are excluded by design.
#>
[CmdletBinding()]
param()

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Push-Location $repoRoot
try {
    Write-Host ''
    Write-Host 'HARSH QUANT OS - secret scan' -ForegroundColor Cyan

    $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $venvPython)) {
        Write-Host '  FAIL  .venv missing - run scripts\setup\setup.ps1' -ForegroundColor Red
        exit 1
    }

    & $venvPython -m pytest tests\security -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host '  FAIL  security suite reported findings' -ForegroundColor Red
        exit 1
    }

    # Windows-side check: is .env tracked by git?
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $tracked = & git ls-files '.env' 2>$null
        if ($tracked) {
            Write-Host '  FAIL  .env is tracked by git' -ForegroundColor Red
            exit 1
        }
        Write-Host '  ok    .env is not tracked' -ForegroundColor Green
    } else {
        Write-Host '  WARN  git not available - tracked-file check skipped' -ForegroundColor Yellow
    }

    Write-Host '  ok    no secret findings' -ForegroundColor Green
    exit 0
}
finally {
    Pop-Location
}
