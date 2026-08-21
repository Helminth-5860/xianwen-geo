param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSha,
    [string]$Repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$env:EXPECTED_SHA = $ExpectedSha

$resolvedRepository = (Resolve-Path -LiteralPath $Repository).Path
$gitRoot = (& git -C $resolvedRepository rev-parse --show-toplevel).Trim()
if ((Resolve-Path -LiteralPath $gitRoot).Path -ne $resolvedRepository) {
    throw 'Repository must be the exact Git worktree root.'
}

$dirty = @(& git -C $resolvedRepository status --porcelain)
if ($dirty.Count -ne 0) {
    throw 'Release preflight requires a clean worktree.'
}
$branch = (& git -C $resolvedRepository branch --show-current).Trim()
if ($branch -ne 'develop') { throw 'Release preflight requires the develop branch.' }

& git -C $resolvedRepository fetch origin develop
if ($LASTEXITCODE -ne 0) { throw 'Unable to fetch origin/develop.' }
$headSha = (& git -C $resolvedRepository rev-parse HEAD).Trim()
$developSha = (& git -C $resolvedRepository rev-parse origin/develop).Trim()
if ($headSha -ne $env:EXPECTED_SHA -or $developSha -ne $env:EXPECTED_SHA) {
    throw 'HEAD and origin/develop must both equal the exact expected SHA.'
}

Push-Location (Join-Path $resolvedRepository 'backend')
try {
    & $Python manage.py migrate --plan --check
    if ($LASTEXITCODE -ne 0) { throw 'Migration plan is not current.' }
    & $Python manage.py release_readiness
    if ($LASTEXITCODE -ne 0) { throw 'Release readiness is NOT_READY.' }
}
finally {
    Pop-Location
}

[ordered]@{
    status = 'READY'
    expected_sha = $env:EXPECTED_SHA
    head_sha = $headSha
    origin_develop_sha = $developSha
    dirty = $false
    branch = $branch
    deployment_performed = $false
} | ConvertTo-Json -Compress
