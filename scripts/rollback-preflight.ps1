param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$CurrentSha,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$TargetSha,
    [Parameter(Mandatory = $true)][string]$BackupArtifact,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$BackupChecksum,
    [string]$Repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$PgRestore = 'pg_restore'
)

$ErrorActionPreference = 'Stop'
$resolvedRepository = (Resolve-Path -LiteralPath $Repository).Path
if (@(& git -C $resolvedRepository status --porcelain).Count -ne 0) {
    throw 'Rollback preflight requires a clean worktree.'
}
if ((& git -C $resolvedRepository rev-parse HEAD).Trim() -ne $CurrentSha) {
    throw 'Current deployed source does not equal CurrentSha.'
}
& git -C $resolvedRepository cat-file -e "$TargetSha`^{commit}"
if ($LASTEXITCODE -ne 0) { throw 'Rollback target commit is unavailable.' }
& git -C $resolvedRepository merge-base --is-ancestor $TargetSha $CurrentSha
if ($LASTEXITCODE -ne 0) { throw 'Rollback target must be an ancestor of CurrentSha.' }
$artifact = (Resolve-Path -LiteralPath $BackupArtifact).Path
if ((Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant() -ne $BackupChecksum) {
    throw 'Rollback backup checksum mismatch.'
}
& $PgRestore --list $artifact | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Rollback backup catalog is invalid.' }
$migrationDiff = @(& git -C $resolvedRepository diff --name-only $TargetSha $CurrentSha -- ':(glob)backend/**/migrations/*.py')
if ($migrationDiff.Count -ne 0) {
    throw 'ROLLBACK_MIGRATION_REVIEW_REQUIRED: migration files differ between target and current SHA.'
}
[ordered]@{status = 'READY'; current_sha = $CurrentSha; target_sha = $TargetSha; backup_verified = $true; migration_diff_count = 0; rollback_performed = $false} | ConvertTo-Json -Compress
