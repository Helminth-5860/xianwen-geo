param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSha,
    [string]$Repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = 'Stop'
$resolvedRepository = (Resolve-Path -LiteralPath $Repository).Path
if (@(& git -C $resolvedRepository status --porcelain).Count -ne 0) {
    throw 'Release source sync requires a clean worktree.'
}
if ((& git -C $resolvedRepository branch --show-current).Trim() -ne 'develop') {
    throw 'Release source sync requires the develop branch.'
}
& git -C $resolvedRepository pull --ff-only origin develop
if ($LASTEXITCODE -ne 0) { throw 'origin/develop did not fast-forward cleanly.' }
$headSha = (& git -C $resolvedRepository rev-parse HEAD).Trim()
$remoteSha = (& git -C $resolvedRepository rev-parse origin/develop).Trim()
if ($headSha -ne $ExpectedSha -or $remoteSha -ne $ExpectedSha) {
    throw 'Synced source does not equal the exact expected SHA.'
}
[ordered]@{status = 'SYNCED'; expected_sha = $ExpectedSha; head_sha = $headSha; ff_only = $true} |
    ConvertTo-Json -Compress
