[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$BackupFile
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$backupPath = [System.IO.Path]::GetFullPath($BackupFile)
$checksumPath = "$backupPath.sha256"
if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
    throw "backup file not found: $backupPath"
}
if (-not (Test-Path -LiteralPath $checksumPath -PathType Leaf)) {
    throw "checksum file not found: $checksumPath"
}

$expected = ((Get-Content -LiteralPath $checksumPath -Raw).Trim() -split '\s+')[0]
$actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $backupPath).Hash
if ($expected -ine $actual) { throw "SHA-256 mismatch for $backupPath" }

$testDb = "weave_restore_$((Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss'))_$PID"
$containerId = (& docker compose -f (Join-Path $repoRoot 'docker-compose.yml') ps -q postgres).Trim()
if ($LASTEXITCODE -ne 0 -or -not $containerId) { throw 'Postgres container is not running' }
$containerDump = "/tmp/$([System.IO.Path]::GetFileName($backupPath))"

Push-Location $repoRoot
try {
    & docker cp $backupPath "${containerId}:$containerDump"
    if ($LASTEXITCODE -ne 0) { throw 'docker cp failed' }
    & docker compose -f docker-compose.yml exec -T postgres createdb --username=weave $testDb
    if ($LASTEXITCODE -ne 0) { throw 'createdb failed' }
    & docker compose -f docker-compose.yml exec -T postgres `
        pg_restore --exit-on-error --no-owner --no-acl --username=weave `
        --dbname=$testDb $containerDump
    if ($LASTEXITCODE -ne 0) { throw 'pg_restore failed' }
    $tableCount = (& docker compose -f docker-compose.yml exec -T postgres `
        psql --username=weave --dbname=$testDb --tuples-only --no-align `
        --command "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';").Trim()
    if ($LASTEXITCODE -ne 0 -or [int]$tableCount -lt 1) {
        throw "restored database has no public tables (reported $tableCount)"
    }
    $migration = (& docker compose -f docker-compose.yml exec -T postgres `
        psql --username=weave --dbname=$testDb --tuples-only --no-align `
        --command 'SELECT version_num FROM alembic_version;').Trim()
    if ($LASTEXITCODE -ne 0 -or -not $migration) {
        throw 'restored database has no Alembic revision'
    }
    Write-Output "restore verification passed: $backupPath (tables=$tableCount, migration=$migration)"
} finally {
    & docker compose -f docker-compose.yml exec -T postgres `
        dropdb --if-exists --force --username=weave $testDb 2>$null | Out-Null
    & docker compose -f docker-compose.yml exec -T postgres `
        rm -f $containerDump 2>$null | Out-Null
    Pop-Location
}
