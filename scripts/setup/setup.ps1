<#
.SYNOPSIS
    HARSH QUANT OS - one-shot development setup (Windows).

.DESCRIPTION
    1. verifies prerequisites and versions
    2. creates the repository directory structure
    3. creates the Python virtual environment
    4. installs Python and npm dependencies
    5. prepares .env from .env.example if missing
    6. runs the validation gate
    7. prints next steps

    Nothing dangerous is installed. Missing optional tools (Docker) are
    reported, not installed.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup\setup.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipChecks,
    [switch]$SkipValidation
)

$ErrorActionPreference = 'Stop'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$failures = New-Object System.Collections.Generic.List[string]

function Step {
    param([int]$Number, [int]$Total, [string]$Text)
    Write-Host ''
    Write-Host ('[{0}/{1}] {2}' -f $Number, $Total, $Text) -ForegroundColor Cyan
}

function Ok   { param([string]$Text) Write-Host ('  ok   ' + $Text) -ForegroundColor Green }
function Warn { param([string]$Text) Write-Host ('  warn ' + $Text) -ForegroundColor Yellow }
function Bad  { param([string]$Text) Write-Host ('  FAIL ' + $Text) -ForegroundColor Red }

Push-Location $repoRoot
try {
    Write-Host ''
    Write-Host 'HARSH QUANT OS - setup' -ForegroundColor Cyan
    Write-Host ('repository: ' + $repoRoot) -ForegroundColor DarkGray

    # ---------------------------------------------------------------
    Step 1 7 'Checking prerequisites'
    # ---------------------------------------------------------------
    if (-not $SkipChecks) {
        $gitCmd = Get-Command git -ErrorAction SilentlyContinue
        if (-not $gitCmd -and (Test-Path 'D:\Git\cmd\git.exe')) {
            $env:Path = 'D:\Git\cmd;' + $env:Path
            Ok 'git located at D:\Git\cmd (added for this session)'
        } elseif ($gitCmd) {
            Ok ('git ' + (& git --version))
        } else {
            Bad 'git not found - install Git for Windows'
            $failures.Add('git missing')
        }

        $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
        if ($nodeCmd) {
            $nodeVersion = (& node -v)
            $major = 0
            if ($nodeVersion -match 'v(\d+)') { $major = [int]$Matches[1] }
            if ($major -ge 20) { Ok ("node " + $nodeVersion) }
            else { Bad ("node " + $nodeVersion + " - 20.11+ required"); $failures.Add('node too old') }
        } else {
            Bad 'node not found'
            $failures.Add('node missing')
        }

        if (Get-Command npm.cmd -ErrorAction SilentlyContinue) { Ok ('npm ' + (& npm.cmd -v)) }
        elseif (Get-Command npm -ErrorAction SilentlyContinue) { Ok ('npm ' + (& npm -v)) }
        else { Bad 'npm not found'; $failures.Add('npm missing') }

        $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCmd) {
            $pyVersion = (& python --version 2>&1 | Out-String).Trim()
            if ($pyVersion -match 'Python 3\.(\d+)') {
                if ([int]$Matches[1] -ge 12) { Ok $pyVersion }
                else { Bad ($pyVersion + ' - 3.12+ required'); $failures.Add('python too old') }
            } else { Warn $pyVersion }
        } else {
            Bad 'python not found'
            $failures.Add('python missing')
        }

        if (Get-Command docker -ErrorAction SilentlyContinue) { Ok 'docker present (optional)' }
        else { Warn 'docker not installed - optional; needed only for local PostgreSQL' }

        if ($failures.Count -gt 0) {
            Write-Host ''
            Write-Host ('Setup cannot continue: ' + ($failures -join ', ')) -ForegroundColor Red
            exit 1
        }
    }

    # ---------------------------------------------------------------
    Step 2 7 'Creating directory structure'
    # ---------------------------------------------------------------
    $directories = @(
        'apps\web', 'apps\api', 'apps\local-agent',
        'packages\types', 'packages\config', 'packages\data', 'packages\quant',
        'packages\risk', 'packages\backtesting', 'packages\shared',
        'agents\architect', 'agents\frontend', 'agents\backend', 'agents\data',
        'agents\quant', 'agents\ai', 'agents\risk', 'agents\security',
        'agents\qa', 'agents\auditor',
        'docs\architecture', 'docs\development', 'docs\security',
        'docs\operations', 'docs\research', 'docs\decisions',
        'research\experiments', 'research\hypotheses', 'research\reports', 'research\notebooks',
        'strategies\candidates', 'strategies\validated', 'strategies\rejected', 'strategies\archived',
        'data\raw', 'data\clean', 'data\features', 'data\exports', 'data\cache',
        'tests\unit', 'tests\integration', 'tests\security', 'tests\data',
        'tests\quant', 'tests\backtesting', 'tests\end-to-end',
        'scripts\setup', 'scripts\development', 'scripts\data', 'scripts\maintenance',
        'infrastructure\docker', 'infrastructure\database',
        'infrastructure\deployment', 'infrastructure\monitoring',
        '.github\workflows'
    )
    $created = 0
    foreach ($dir in $directories) {
        $full = Join-Path $repoRoot $dir
        if (-not (Test-Path $full)) {
            New-Item -ItemType Directory -Path $full -Force | Out-Null
            $created++
        }
    }
    Ok ("$created new directory(ies); " + ($directories.Count - $created) + ' already present')

    # Ensure placeholder files keep empty directories in Git
    foreach ($dir in @('data\raw', 'data\clean', 'data\features', 'data\exports', 'data\cache',
                       'research\experiments', 'research\hypotheses', 'research\reports',
                       'research\notebooks', 'strategies\candidates', 'strategies\validated',
                       'strategies\rejected', 'strategies\archived')) {
        $keep = Join-Path $repoRoot ($dir + '\.gitkeep')
        if (-not (Test-Path $keep)) { New-Item -ItemType File -Path $keep -Force | Out-Null }
    }

    # ---------------------------------------------------------------
    Step 3 7 'Creating Python virtual environment'
    # ---------------------------------------------------------------
    $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (Test-Path $venvPython) {
        Ok '.venv already exists'
    } else {
        & python -m venv .venv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
            Bad 'failed to create .venv'
            exit 1
        }
        Ok 'created .venv'
    }

    # ---------------------------------------------------------------
    Step 4 7 'Installing Python dependencies'
    # ---------------------------------------------------------------
    & $venvPython -m pip install --upgrade pip --quiet
    & $venvPython -m pip install -e ".[dev]" --quiet
    if ($LASTEXITCODE -ne 0) { Bad 'pip install failed'; exit 1 }
    Ok 'installed project + dev extras (editable)'

    # ---------------------------------------------------------------
    Step 5 7 'Installing npm dependencies'
    # ---------------------------------------------------------------
    if (Get-Command npm.cmd -ErrorAction SilentlyContinue) {
        & npm.cmd install --no-fund
    } else {
        & npm install --no-fund
    }
    if ($LASTEXITCODE -ne 0) { Bad 'npm install failed'; exit 1 }
    Ok 'installed npm workspaces'

    # ---------------------------------------------------------------
    Step 6 7 'Preparing configuration'
    # ---------------------------------------------------------------
    $envExample = Join-Path $repoRoot '.env.example'
    $envFile = Join-Path $repoRoot '.env'
    if (-not (Test-Path $envFile)) {
        if (Test-Path $envExample) {
            Copy-Item $envExample $envFile
            Ok 'created .env from .env.example (placeholders only - replace before use)'
        } else {
            Bad '.env.example missing'
            exit 1
        }
    } else {
        Ok '.env already exists - left untouched'
    }

    if (Get-Command git.cmd -ErrorAction SilentlyContinue -or (Get-Command git -ErrorAction SilentlyContinue)) {
        $tracked = & git ls-files '.env' 2>$null
        if ($tracked) { Bad '.env is tracked by git - untrack it immediately' }
        else { Ok '.env is not tracked by git' }
    }

    # ---------------------------------------------------------------
    Step 7 7 'Running validation'
    # ---------------------------------------------------------------
    if ($SkipValidation) {
        Warn 'validation skipped (-SkipValidation)'
    } else {
        $checks = New-Object System.Collections.Generic.List[object]
        $checks.Add(@{ Name = 'prettier'; Cmd = { & npx.cmd prettier --check . 2>&1 | Out-String } })
        $checks.Add(@{ Name = 'eslint';   Cmd = { & npx.cmd eslint . 2>&1 | Out-String } })
        $checks.Add(@{ Name = 'tsc';      Cmd = { & npx.cmd tsc --noEmit -p tsconfig.json 2>&1 | Out-String } })
        $checks.Add(@{ Name = 'vitest';   Cmd = { & npx.cmd vitest run 2>&1 | Out-String } })
        $checks.Add(@{ Name = 'ruff';     Cmd = { & $venvPython -m ruff check . 2>&1 | Out-String } })
        $checks.Add(@{ Name = 'mypy';     Cmd = { & $venvPython -m mypy 2>&1 | Out-String } })
        $checks.Add(@{ Name = 'pytest';   Cmd = { & $venvPython -m pytest -q 2>&1 | Out-String } })

        foreach ($check in $checks) {
            $output = & $check.Cmd
            if ($LASTEXITCODE -eq 0) { Ok ($check.Name + ' passed') }
            else {
                Bad ($check.Name + ' failed')
                Write-Host ($output -replace '(?m)^', '       ') -ForegroundColor DarkRed
                $failures.Add($check.Name)
            }
        }
    }

    Write-Host ''
    if ($failures.Count -gt 0) {
        Write-Host ('Setup finished with failures: ' + ($failures -join ', ')) -ForegroundColor Red
        Write-Host 'Fix the failures above and re-run setup.' -ForegroundColor Red
        exit 1
    }

    Write-Host 'Setup complete.' -ForegroundColor Green
    Write-Host ''
    Write-Host 'Next steps:' -ForegroundColor Cyan
    Write-Host '  1. Review .env and replace placeholder values when a subsystem needs them.'
    Write-Host '  2. Run the health check:'
    Write-Host '       powershell -NoProfile -ExecutionPolicy Bypass -File scripts\development\health-check.ps1'
    Write-Host '  3. Run all checks whenever you change code:'
    Write-Host '       npm run check'
    Write-Host '  4. Read AGENTS.md before writing any code.'
    Write-Host '  5. Current phase is 0 (Foundation). Do not start Phase 1 until told to.'
    Write-Host ''
    exit 0
}
finally {
    Pop-Location
}
