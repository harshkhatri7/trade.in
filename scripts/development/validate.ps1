<#
.SYNOPSIS
    HARSH QUANT OS - run the full validation gate and report real results.

.DESCRIPTION
    Runs formatting, linting, type checking and both test suites. Prints a
    PASS/FAIL line per check with the exit code actually observed.

    Exit code 0 only when every check passed.
#>
[CmdletBinding()]
param(
    [switch]$PythonOnly,
    [switch]$TypeScriptOnly
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Push-Location $repoRoot
try {
    $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
    $results = New-Object System.Collections.Generic.List[object]

    function Invoke-Check {
        param([string]$Name, [scriptblock]$Body)
        $output = & $Body 2>&1 | Out-String
        $code = $LASTEXITCODE
        $results.Add([pscustomobject]@{ Name = $Name; Code = $code; Output = $output })
        if ($code -eq 0) {
            Write-Host ('PASS  ' + $Name) -ForegroundColor Green
        } else {
            Write-Host ('FAIL  ' + $Name + ' (exit ' + $code + ')') -ForegroundColor Red
            Write-Host ($output -replace '(?m)^', '      ') -ForegroundColor DarkRed
        }
    }

    if (-not $PythonOnly) {
        Write-Host 'TypeScript checks' -ForegroundColor Cyan
        Invoke-Check 'prettier --check' { & npx.cmd prettier --check . }
        Invoke-Check 'eslint'            { & npx.cmd eslint . }
        Invoke-Check 'tsc --noEmit'      { & npx.cmd tsc --noEmit -p tsconfig.json }
        Invoke-Check 'vitest run'        { & npx.cmd vitest run }
    }

    if (-not $TypeScriptOnly) {
        Write-Host 'Python checks' -ForegroundColor Cyan
        if (-not (Test-Path $venvPython)) {
            Write-Host 'FAIL  .venv missing - run scripts\setup\setup.ps1' -ForegroundColor Red
            $results.Add([pscustomobject]@{ Name = '.venv'; Code = 1; Output = 'missing' })
        } else {
            Invoke-Check 'ruff format --check' { & $venvPython -m ruff format --check . }
            Invoke-Check 'ruff check'          { & $venvPython -m ruff check . }
            Invoke-Check 'mypy'                { & $venvPython -m mypy }
            Invoke-Check 'pytest'              { & $venvPython -m pytest -q }
        }
    }

    Write-Host ''
    $failed = @($results | Where-Object { $_.Code -ne 0 })
    if ($failed.Count -eq 0) {
        Write-Host ('ALL CHECKS PASSED (' + $results.Count + ' checks)') -ForegroundColor Green
        exit 0
    }
    Write-Host ($failed.Count.ToString() + ' of ' + $results.Count.ToString() + ' checks FAILED: ' +
        (($failed | ForEach-Object { $_.Name }) -join ', ')) -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
