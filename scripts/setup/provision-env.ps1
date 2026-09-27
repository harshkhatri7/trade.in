<#
.SYNOPSIS
    HARSH QUANT OS - fill local .env placeholders with generated values.

.DESCRIPTION
    Replaces template placeholders in .env with values generated on this machine
    and makes sure the CORS allow-list covers both loopback origins.

    Run this script yourself. AGENTS.md section 3 forbids an agent from writing
    .env, so this script is the supported path: an agent can supply it, but only
    a human executes it.

    Values are never printed. The report names the keys that changed and which
    keys still hold a placeholder - never the contents.

    .env must stay untracked; the script aborts if git has it staged.

    With -Force every generated secret is rotated, including ones already set.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup\provision-env.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup\provision-env.ps1 -Force
#>
[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$envFile = Join-Path $repoRoot '.env'
$envExample = Join-Path $repoRoot '.env.example'

function Ok   { param([string]$Text) Write-Host ('  ok   ' + $Text) -ForegroundColor Green }
function Warn { param([string]$Text) Write-Host ('  warn ' + $Text) -ForegroundColor Yellow }
function Bad  { param([string]$Text) Write-Host ('  FAIL ' + $Text) -ForegroundColor Red }

# URL-safe, case-sensitive, no padding: safe inside a connection string.
function New-SecretValue {
    param([int]$ByteLength)
    $bytes = New-Object byte[] $ByteLength
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    $b64 = [Convert]::ToBase64String($bytes)
    return (($b64 -replace '\+', '-') -replace '/', '_') -replace '=', ''
}

function Test-Placeholder {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $true }
    return ($Value -like '*replace-with*')
}

Push-Location $repoRoot
try {
    Write-Host ''
    Write-Host 'HARSH QUANT OS - local environment provisioning' -ForegroundColor Cyan

    if (-not (Test-Path $envFile)) {
        if (-not (Test-Path $envExample)) {
            Bad '.env.example is missing - cannot create .env'
            exit 1
        }
        Copy-Item $envExample $envFile
        Ok 'created .env from .env.example'
    }

    # The script writes a secret-bearing file; refuse if that file is committed.
    $envPathspec = $envFile.Substring($repoRoot.Path.Length + 1) -replace '\\', '/'
    $gitCmd = Get-Command git -ErrorAction SilentlyContinue
    if (-not $gitCmd -and (Test-Path 'D:\Git\cmd\git.exe')) {
        $env:Path = 'D:\Git\cmd;' + $env:Path
    }
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $tracked = @()
        try {
            # Native stderr becomes an ErrorRecord under $ErrorActionPreference
            # 'Stop'; swallow it rather than aborting on git's own chatter.
            $tracked = @(git ls-files -- $envPathspec 2>$null)
        }
        catch {
            $tracked = @()
        }
        if ($tracked.Count -gt 0) {
            Bad '.env is tracked by git - untrack it before provisioning'
            exit 1
        }
        Ok '.env is not tracked by git'
    }

    $raw = [System.IO.File]::ReadAllText($envFile)
    $eol = if ($raw.Contains("`r`n")) { "`r`n" } else { "`n" }
    $lines = New-Object 'System.Collections.Generic.List[string]'
    foreach ($line in ($raw -split "`r?`n")) { $lines.Add($line) }
    # Drop the empty element produced by a trailing newline.
    if ($lines.Count -gt 0 -and $lines[$lines.Count - 1] -eq '') {
        $lines.RemoveAt($lines.Count - 1)
    }

    $index = @{}
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^(?<k>[A-Za-z_][A-Za-z0-9_]*)=(?<v>.*)$') {
            $index[$Matches['k']] = $i
        }
    }

    # Both helpers mutate the shared list in place: a `$lines +=` here would
    # silently create a function-local copy and lose the appended key.
    function Set-EnvValue {
        param([string]$Key, [string]$Value)
        if ($index.ContainsKey($Key)) {
            $lines[$index[$Key]] = ($Key + '=' + $Value)
        }
        else {
            $index[$Key] = $lines.Count
            $lines.Add($Key + '=' + $Value)
        }
    }

    function Get-EnvValue {
        param([string]$Key)
        if ($index.ContainsKey($Key)) { return $lines[$index[$Key]] -replace '^[^=]*=', '' }
        return $null
    }

    $changed = New-Object System.Collections.Generic.List[string]

    # --- Secrets ------------------------------------------------------
    foreach ($secret in @(
            @{ Key = 'AUTH_SECRET_KEY'; Bytes = 48; Why = 'signs sessions' },
            @{ Key = 'DATABASE_PASSWORD'; Bytes = 24; Why = 'local PostgreSQL role' }
        )) {
        $current = Get-EnvValue $secret.Key
        if ($Force -or (Test-Placeholder $current)) {
            Set-EnvValue $secret.Key (New-SecretValue $secret.Bytes)
            $changed.Add($secret.Key + ' (generated; ' + $secret.Why + ')')
        }
    }

    # --- Connection string derived from the individual DATABASE_* keys ---
    $dbHost = Get-EnvValue 'DATABASE_HOST'
    $dbPort = Get-EnvValue 'DATABASE_PORT'
    $dbName = Get-EnvValue 'DATABASE_NAME'
    $dbUser = Get-EnvValue 'DATABASE_USER'
    $dbPass = Get-EnvValue 'DATABASE_PASSWORD'
    $dbUrl  = Get-EnvValue 'DATABASE_URL'
    if ($dbHost -and $dbPort -and $dbName -and $dbUser -and $dbPass) {
        if ($Force -or (Test-Placeholder $dbUrl) -or $changed -contains 'DATABASE_PASSWORD (generated; local PostgreSQL role)') {
            $encodedUser = [uri]::EscapeDataString($dbUser)
            $encodedPass = [uri]::EscapeDataString($dbPass)
            Set-EnvValue 'DATABASE_URL' (
                'postgresql+asyncpg://' + $encodedUser + ':' + $encodedPass +
                '@' + $dbHost + ':' + $dbPort + '/' + $dbName
            )
            $changed.Add('DATABASE_URL (rebuilt from DATABASE_HOST/PORT/NAME/USER/PASSWORD)')
        }
    }

    # --- CORS allow-list ------------------------------------------------
    $requiredOrigins = @('http://localhost:3000', 'http://127.0.0.1:3000')
    $current = Get-EnvValue 'API_ALLOWED_ORIGINS'
    $origins = @()
    if ($current) { $origins = @($current -split ',') | ForEach-Object { $_.Trim() } | Where-Object { $_ } }
    $merged = @($requiredOrigins + $origins) | Select-Object -Unique
    $mergedText = ($merged -join ',')
    if ($mergedText -ne $current) {
        Set-EnvValue 'API_ALLOWED_ORIGINS' $mergedText
        $changed.Add('API_ALLOWED_ORIGINS (now covers both loopback origins)')
    }

    # --- Write atomically, no BOM, original line endings -----------------
    $tmpFile = $envFile + '.tmp'
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($tmpFile, (($lines -join $eol) + $eol), $utf8NoBom)
    Move-Item -Path $tmpFile -Destination $envFile -Force

    if ($changed.Count -gt 0) {
        foreach ($item in $changed) { Ok $item }
    }
    else {
        Ok 'nothing to do - every handled key was already set'
    }

    # --- Read back what actually landed on disk -------------------------
    # In-memory state proves nothing; the next run reads this file.
    $written = @{}
    foreach ($line in [System.IO.File]::ReadAllText($envFile) -split "`r?`n") {
        if ($line -match '^(?<k>[A-Za-z_][A-Za-z0-9_]*)=(?<v>.*)$') {
            $written[$Matches['k']] = $Matches['v']
        }
    }

    $checks = New-Object System.Collections.Generic.List[string]
    if ($written.ContainsKey('AUTH_SECRET_KEY') -and -not (Test-Placeholder $written['AUTH_SECRET_KEY'])) {
        $checks.Add('ok   AUTH_SECRET_KEY has a generated value')
    }
    else { $checks.Add('FAIL AUTH_SECRET_KEY is still a placeholder') }

    if ($written.ContainsKey('DATABASE_PASSWORD') -and -not (Test-Placeholder $written['DATABASE_PASSWORD'])) {
        $checks.Add('ok   DATABASE_PASSWORD has a generated value')
    }
    else { $checks.Add('FAIL DATABASE_PASSWORD is still a placeholder') }

    $urlOk = $written.ContainsKey('DATABASE_URL') -and
             $written.ContainsKey('DATABASE_PASSWORD') -and
             $written['DATABASE_URL'].Contains($written['DATABASE_PASSWORD'])
    if ($urlOk) { $checks.Add('ok   DATABASE_URL and DATABASE_PASSWORD agree') }
    else { $checks.Add('FAIL DATABASE_URL does not carry DATABASE_PASSWORD') }

    $originsOk = $written.ContainsKey('API_ALLOWED_ORIGINS')
    if ($originsOk) {
        $have = @($written['API_ALLOWED_ORIGINS'] -split ',') | ForEach-Object { $_.Trim() }
        $originsOk = $have -contains 'http://localhost:3000' -and $have -contains 'http://127.0.0.1:3000'
    }
    if ($originsOk) { $checks.Add('ok   API_ALLOWED_ORIGINS covers both loopback origins') }
    else { $checks.Add('FAIL API_ALLOWED_ORIGINS is missing a loopback origin') }

    $keysBefore = @($index.Keys).Count
    if ($written.Count -ge $keysBefore) { $checks.Add("ok   no key lost ($keysBefore before, $($written.Count) after)") }
    else { $checks.Add("FAIL $($keysBefore - $written.Count) key(s) disappeared") }

    Write-Host ''
    foreach ($check in $checks) {
        if ($check.StartsWith('ok')) { Ok $check.Substring(4) }
        else { Bad $check.Substring(5) }
    }
    if (@($checks | Where-Object { $_.StartsWith('FAIL') }).Count -gt 0) {
        Write-Host ''
        Bad 'provisioning did not verify - inspect .env before continuing'
        exit 1
    }

    # Honest list of what is still a placeholder; names only.
    $remaining = @()
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^(?<k>[A-Za-z_][A-Za-z0-9_]*)=(?<v>.*)$') {
            if (Test-Placeholder $Matches['v']) { $remaining += $Matches['k'] }
        }
    }
    if ($remaining.Count -gt 0) {
        Warn ('still placeholder (replace when that subsystem is used): ' + ($remaining -join ', '))
    }

    Write-Host ''
    Write-Host 'Values were not printed and are not stored anywhere but .env.' -ForegroundColor DarkGray
    Write-Host 'Next: npm run db:start' -ForegroundColor DarkGray
    Write-Host ''
    exit 0
}
finally {
    Pop-Location
}
