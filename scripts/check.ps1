$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendPython = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $backendPython)) {
    throw "Create backend/.venv and install requirements-dev.txt first."
}


Push-Location (Join-Path $repoRoot "backend")
try {
    & $backendPython -m ruff check .
    & $backendPython -m ruff format --check .
    & $backendPython -m pytest
    & $backendPython -m openapi_spec_validator ..\openapi\openapi-v1.yaml
}
finally {
    Pop-Location
}

Push-Location (Join-Path $repoRoot "frontend")
try {
    npm run lint
    npm run format:check
    npm run typecheck
    npm test
}
finally {
    Pop-Location
}
