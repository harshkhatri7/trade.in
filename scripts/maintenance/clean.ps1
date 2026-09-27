<#
.SYNOPSIS
    HARSH QUANT OS - clean generated artefacts.

.DESCRIPTION
    Removes caches and build output ONLY, from an explicit allow-list of
    paths inside the repository. Source, documentation, configuration and
    datasets are never touched.

    Use -WhatIf-style confirmation: without -Force the script only lists what
    it would remove.
#>
[CmdletBinding()]
param(
    [switch]$Force
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$targets = @(
    'node_modules\.cache',
    'coverage',
    '.pytest_cache',
    '.mypy_cache',
    '.ruff_cache',
    'dist',
    'build',
    '.next',
    'logs'
)

Push-Location $repoRoot
try {
    Write-Host ''
    Write-Host 'HARSH QUANT OS - clean generated artefacts' -ForegroundColor Cyan

    $found = @()
    foreach ($target in $targets) {
        $full = Join-Path $repoRoot $target
        if (Test-Path $full) { $found += $full }
    }

    if ($found.Count -eq 0) {
        Write-Host '  nothing to clean' -ForegroundColor Green
        exit 0
    }

    foreach ($path in $found) {
        $rel = $path.Substring($repoRoot.Path.Length).TrimStart('\')
        if ($Force) {
            try {
                Remove-Item -Path $path -Recurse -Force -ErrorAction Stop
                Write-Host ('  removed ' + $rel) -ForegroundColor Green
            } catch {
                Write-Host ('  FAILED  ' + $rel + ' - ' + $_.Exception.Message) -ForegroundColor Red
            }
        } else {
            Write-Host ('  would remove ' + $rel) -ForegroundColor Yellow
        }
    }

    if (-not $Force) {
        Write-Host ''
        Write-Host '  Re-run with -Force to actually delete the paths above.' -ForegroundColor Yellow
        exit 0
    }

    Write-Host ''
    Write-Host '  Python caches can be recreated with: .\.venv\Scripts\python.exe -m pytest -q' -ForegroundColor DarkGray
    Write-Host '  Never clean data\ - datasets are not generated artefacts.' -ForegroundColor DarkGray
    exit 0
}
finally {
    Pop-Location
}
