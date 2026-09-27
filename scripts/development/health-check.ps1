<#
.SYNOPSIS
    HARSH QUANT OS - environment health check.

.DESCRIPTION
    Reports the ACTUAL state of the development environment. A check that
    cannot be executed is reported as UNKNOWN, never as passing.

    Exit codes:
      0  no failures (warnings and info are allowed)
      1  at least one check failed

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\development\health-check.ps1
#>
[CmdletBinding()]
param(
    [switch]$Quiet
)

$ErrorActionPreference = 'SilentlyContinue'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')

$script:passCount = 0
$script:warnCount = 0
$script:failCount = 0

function Write-Result {
    param([ValidateSet('PASS', 'FAIL', 'WARN', 'INFO', 'UNKNOWN')][string]$Status, [string]$Name, [string]$Detail = '')
    switch ($Status) {
        'PASS' { $script:passCount++; $color = 'Green' }
        'FAIL' { $script:failCount++; $color = 'Red' }
        'WARN' { $script:warnCount++; $color = 'Yellow' }
        'INFO' { $color = 'Gray' }
        'UNKNOWN' { $script:warnCount++; $color = 'DarkYellow' }
    }
    $line = ('{0,-8} {1,-34} {2}' -f $Status, $Name, $Detail)
    Write-Host $line -ForegroundColor $color
}

function Get-ToolPath {
    param([string]$Name)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

Push-Location $repoRoot
try {
    if (-not $Quiet) {
        Write-Host ''
        Write-Host 'HARSH QUANT OS - health check' -ForegroundColor Cyan
        Write-Host ('repository : ' + $repoRoot) -ForegroundColor DarkGray
        Write-Host ('timestamp  : ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -ForegroundColor DarkGray
        Write-Host ''
    }

    # ---------------- platform ----------------
    $os = [System.Environment]::OSVersion.VersionString
    $arch = $env:PROCESSOR_ARCHITECTURE
    Write-Result 'INFO' 'Operating system' $os
    Write-Result 'INFO' 'Architecture' $arch
    Write-Result 'INFO' 'PowerShell' $PSVersionTable.PSVersion.ToString()

    # ---------------- git ----------------
    $gitPath = Get-ToolPath 'git'
    if (-not $gitPath) {
        foreach ($candidate in @('D:\Git\cmd\git.exe', 'C:\Program Files\Git\cmd\git.exe', "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe")) {
            if (Test-Path $candidate) { $gitPath = $candidate; break }
        }
    }
    if ($gitPath) {
        $gitVersion = (& $gitPath --version 2>$null)
        Write-Result 'PASS' 'Git' "$gitVersion ($gitPath)"
    } else {
        Write-Result 'FAIL' 'Git' 'not found on PATH and not in a known location'
    }

    # ---------------- node ----------------
    if (Test-Command 'node') {
        $nodeVersion = (& node -v 2>$null)
        $major = 0
        if ($nodeVersion -match 'v(\d+)') { $major = [int]$Matches[1] }
        if ($major -ge 20) {
            Write-Result 'PASS' 'Node.js' $nodeVersion
        } else {
            Write-Result 'FAIL' 'Node.js' "$nodeVersion - 20.11+ required"
        }
    } else {
        Write-Result 'FAIL' 'Node.js' 'not found on PATH'
    }

    $npmCmd = Get-ToolPath 'npm.cmd'
    if (-not $npmCmd) { $npmCmd = Get-ToolPath 'npm' }
    if ($npmCmd) {
        $npmVersion = (& $npmCmd -v 2>$null)
        Write-Result 'PASS' 'npm' $npmVersion
    } else {
        Write-Result 'FAIL' 'npm' 'not found on PATH'
    }

    # ---------------- python ----------------
    $pythonCmd = Get-ToolPath 'python'
    if ($pythonCmd) {
        $pythonVersion = (& $pythonCmd --version 2>&1 | Out-String).Trim()
        if ($pythonVersion -match 'Python 3\.(\d+)') {
            $minor = [int]$Matches[1]
            if ($minor -ge 12) { Write-Result 'PASS' 'Python' "$pythonVersion ($pythonCmd)" }
            else { Write-Result 'FAIL' 'Python' "$pythonVersion - 3.12+ required" }
        } else {
            Write-Result 'WARN' 'Python' $pythonVersion
        }
    } else {
        Write-Result 'FAIL' 'Python' 'not found on PATH'
    }

    # ---------------- virtual environment ----------------
    $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (Test-Path $venvPython) {
        Write-Result 'PASS' 'Virtual environment' '.venv'
        foreach ($module in @('pytest', 'ruff', 'mypy', 'pydantic', 'fastapi')) {
            if ($module -in @('ruff', 'mypy')) {
                $out = (& $venvPython -m $module --version 2>$null | Out-String).Trim()
            } else {
                $out = (& $venvPython -c "import $module, sys; sys.stdout.write(getattr($module, '__version__', 'ok'))" 2>$null)
            }
            if ($LASTEXITCODE -eq 0 -and $out) {
                Write-Result 'PASS' ("  python module: " + $module) $out
            } else {
                Write-Result 'FAIL' ("  python module: " + $module) 'not installed (run scripts\setup\setup.ps1)'
            }
        }
        $pkgInstalled = (& $venvPython -c "import harsh_quant_os, sys; sys.stdout.write(harsh_quant_os.__version__)" 2>$null)
        if ($pkgInstalled) { Write-Result 'PASS' 'Foundation package' "harsh_quant_os $pkgInstalled" }
        else { Write-Result 'FAIL' 'Foundation package' 'not importable (run scripts\setup\setup.ps1)' }
    } else {
        Write-Result 'FAIL' 'Virtual environment' '.venv missing (run scripts\setup\setup.ps1)'
    }

    # ---------------- node dependencies ----------------
    if (Test-Path (Join-Path $repoRoot 'node_modules')) {
        Write-Result 'PASS' 'node_modules' 'present'
        foreach ($tool in @('eslint', 'tsc', 'vitest', 'prettier')) {
            $bin = Join-Path $repoRoot ("node_modules\.bin\" + $tool + '.cmd')
            if (Test-Path $bin) { Write-Result 'PASS' ("  npm tool: " + $tool) 'installed' }
            else { Write-Result 'FAIL' ("  npm tool: " + $tool) 'missing (run npm install)' }
        }
    } else {
        Write-Result 'FAIL' 'node_modules' 'missing (run npm install)'
    }

    # ---------------- git repository ----------------
    if ($gitPath) {
        $inside = (& $gitPath rev-parse --is-inside-work-tree 2>$null)
        if ($inside -eq 'true') {
            $hasCommit = (& $gitPath rev-parse --verify HEAD 2>$null)
            if ($hasCommit) {
                $branch = (& $gitPath rev-parse --abbrev-ref HEAD 2>$null)
                Write-Result 'PASS' 'Git repository' "branch $branch"
            } else {
                $branch = (& $gitPath symbolic-ref --short HEAD 2>$null)
                if (-not $branch) { $branch = 'main' }
                Write-Result 'PASS' 'Git repository' "branch $branch (no commits yet)"
            }
            $dirty = (& $gitPath status --porcelain 2>$null)
            if ($dirty) {
                Write-Result 'INFO' 'Working tree' (($dirty | Measure-Object).Count.ToString() + ' changed path(s)')
            } else {
                Write-Result 'PASS' 'Working tree' 'clean'
            }
            $trackedEnv = (& $gitPath ls-files '.env' 2>$null)
            if ($trackedEnv) { Write-Result 'FAIL' '.env tracked by git' 'must be removed from the index' }
            else { Write-Result 'PASS' '.env tracked by git' 'not tracked' }
        } else {
            Write-Result 'WARN' 'Git repository' 'not initialised'
        }
    }

    # ---------------- environment file ----------------
    $envFile = Join-Path $repoRoot '.env'
    if (Test-Path $envFile) {
        $content = Get-Content $envFile -Raw
        if ($content -match '(?im)^LIVE_TRADING_ENABLED\s*=\s*true') {
            Write-Result 'FAIL' 'LIVE_TRADING_ENABLED in .env' 'true - must be false'
        } else {
            Write-Result 'PASS' '.env present' 'live trading flag is not enabled'
        }
    } else {
        Write-Result 'WARN' '.env' 'not created yet (Copy-Item .env.example .env)'
    }

    # ---------------- docker (optional) ----------------
    if (Test-Command 'docker') {
        $dockerVersion = (& docker -v 2>$null)
        $dockerUp = (& docker info --format '{{.ServerVersion}}' 2>$null)
        if ($dockerUp) { Write-Result 'PASS' 'Docker' "$dockerVersion (daemon running)" }
        else { Write-Result 'WARN' 'Docker' "$dockerVersion (daemon not running) - optional" }
        if (Test-Command 'docker') {
            $composeVersion = (& docker compose version 2>$null)
            if ($composeVersion) { Write-Result 'PASS' 'Docker Compose' $composeVersion }
            else { Write-Result 'WARN' 'Docker Compose' 'not available - optional' }
        }
    } else {
        Write-Result 'WARN' 'Docker' 'not installed - optional, required only for local PostgreSQL'
    }

    # ---------------- repository layout ----------------
    foreach ($required in @('README.md', 'AGENTS.md', 'ARCHITECTURE.md', 'SECURITY.md', 'pyproject.toml', 'package.json')) {
        if (Test-Path (Join-Path $repoRoot $required)) { Write-Result 'PASS' ("  root file: " + $required) 'present' }
        else { Write-Result 'FAIL' ("  root file: " + $required) 'missing' }
    }

    # ---------------- summary ----------------
    Write-Host ''
    $summary = ('SUMMARY  pass={0}  warn={1}  fail={2}' -f $script:passCount, $script:warnCount, $script:failCount)
    if ($script:failCount -gt 0) {
        Write-Host $summary -ForegroundColor Red
        Write-Host 'Result: FAIL - resolve the items above, then re-run.' -ForegroundColor Red
        exit 1
    }
    if ($script:warnCount -gt 0) {
        Write-Host $summary -ForegroundColor Yellow
        Write-Host 'Result: PASS with warnings - review the WARN/UNKNOWN items above.' -ForegroundColor Yellow
        exit 0
    }
    Write-Host $summary -ForegroundColor Green
    Write-Host 'Result: PASS' -ForegroundColor Green
    exit 0
}
finally {
    Pop-Location
}
