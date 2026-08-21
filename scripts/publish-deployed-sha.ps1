param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSha,
    [Parameter(Mandatory = $true)][string]$MarkerPath,
    [string]$Repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$resolvedRepository = (Resolve-Path -LiteralPath $Repository).Path
if (@(& git -C $resolvedRepository status --porcelain).Count -ne 0) { throw 'Marker publication requires a clean worktree.' }
if ((& git -C $resolvedRepository rev-parse HEAD).Trim() -ne $ExpectedSha) { throw 'HEAD does not equal ExpectedSha.' }
Push-Location (Join-Path $resolvedRepository 'backend')
try {
    & $Python manage.py release_readiness
    if ($LASTEXITCODE -ne 0) { throw 'Release readiness is NOT_READY; marker was not written.' }
}
finally { Pop-Location }
$parent = Split-Path -Parent $MarkerPath
if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw 'Marker parent directory must already exist.' }
$temporary = Join-Path $parent ([IO.Path]::GetRandomFileName())
try {
    [IO.File]::WriteAllText($temporary, "$ExpectedSha`n", [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $MarkerPath -Force
}
finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force } }
[ordered]@{status = 'PUBLISHED'; deployed_sha = $ExpectedSha; atomic_write = $true; rollout_performed = $false} | ConvertTo-Json -Compress
