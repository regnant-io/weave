[CmdletBinding()]
param([string]$BackupDir)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $BackupDir) { $BackupDir = Join-Path $repoRoot 'backups' }
$backupPath = [System.IO.Path]::GetFullPath($BackupDir)
[System.IO.Directory]::CreateDirectory($backupPath) | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$target = Join-Path $backupPath "weave-$stamp.dump"

Push-Location $repoRoot
try {
    # PowerShell 7.4+ preserves byte streams from native commands when redirecting.
    & docker compose -f docker-compose.yml exec -T postgres `
        pg_dump --format=custom --no-owner --no-acl --username=weave weave > $target
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$target.sha256" -Value "$hash  $target" -Encoding ascii
Write-Output $target
