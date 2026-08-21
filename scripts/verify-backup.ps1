param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSha,
    [Parameter(Mandatory = $true)][string]$Artifact,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedChecksum,
    [string]$Repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$PgRestore = 'pg_restore'
)

$ErrorActionPreference = 'Stop'
$env:EXPECTED_SHA = $ExpectedSha
$resolvedRepository = (Resolve-Path -LiteralPath $Repository).Path
$dirty = @(& git -C $resolvedRepository status --porcelain)
if ($dirty.Count -ne 0) { throw 'Backup verification requires a clean worktree.' }
$headSha = (& git -C $resolvedRepository rev-parse HEAD).Trim()
if ($headSha -ne $env:EXPECTED_SHA) { throw 'Backup verification SHA does not match HEAD.' }

$resolvedArtifact = (Resolve-Path -LiteralPath $Artifact).Path
$actualChecksum = (Get-FileHash -LiteralPath $resolvedArtifact -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualChecksum -ne $ExpectedChecksum) { throw 'Backup checksum mismatch.' }
& $PgRestore --list $resolvedArtifact | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'pg_restore catalog verification failed.' }

[ordered]@{
    status = 'VERIFIED'
    expected_sha = $env:EXPECTED_SHA
    checksum_match = $true
    pg_restore_catalog = 'valid'
    backup_created = $false
} | ConvertTo-Json -Compress
