param(
    [ValidateSet(
        "all",
        "backend",
        "frontend",
        "git",
        "security",
        "actionlint",
        "gitleaks",
        "docker"
    )]
    [string]$Mode = "all"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$actionlintImage = "rhysd/actionlint:1.7.12"
$gitleaksImage = "zricethezav/gitleaks:v8.30.1"

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$Arguments = @()
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE."
    }
}

function Get-BackendPython {
    $candidates = @(
        (Join-Path $repoRoot "backend\.venv\Scripts\python.exe"),
        (Join-Path $repoRoot "backend\.venv\bin\python")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    $command = Get-Command python3, python -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command) {
        throw "Python 3.12 is required."
    }
    return $command.Source
}

function Invoke-BackendChecks {
    $python = Get-BackendPython
    Invoke-External $python @(
        "-c",
        "import sys; assert sys.version_info[:2] == (3, 12), 'Python 3.12 is required'"
    )

    Push-Location (Join-Path $repoRoot "backend")
    try {
        # ruff check
        Invoke-External $python @("-m", "ruff", "check", ".")
        # ruff format --check
        Invoke-External $python @("-m", "ruff", "format", "--check", ".")
        # mypy
        Invoke-External $python @("-m", "mypy")
        # manage.py check
        Invoke-External $python @("manage.py", "check", "--settings=config.django_settings.test")
        # makemigrations --check --dry-run
        Invoke-External $python @(
            "manage.py",
            "makemigrations",
            "--check",
            "--dry-run",
            "--settings=config.django_settings.test"
        )
        # pytest
        Invoke-External $python @("-m", "pytest")
        # openapi_spec_validator
        Invoke-External $python @("-m", "openapi_spec_validator", "..\openapi\openapi-v1.yaml")
        # pip_audit
        Invoke-External $python @("-m", "pip_audit", "-r", "requirements-dev.txt")
    }
    finally {
        Pop-Location
    }
}

function Invoke-FrontendChecks {
    $expectedNode = "v$((Get-Content -Raw (Join-Path $repoRoot "frontend\.nvmrc")).Trim())"
    $actualNode = (& node --version).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "node --version failed."
    }
    if ($actualNode -ne $expectedNode) {
        throw "Expected Node.js $expectedNode, got $actualNode."
    }

    Push-Location (Join-Path $repoRoot "frontend")
    try {
        # npm run lint
        Invoke-External "npm" @("run", "lint")
        # npm run format:check
        Invoke-External "npm" @("run", "format:check")
        # npm run typecheck
        Invoke-External "npm" @("run", "typecheck")
        # npm test
        Invoke-External "npm" @("test")
        # npm run build
        Invoke-External "npm" @("run", "build")
        # npm audit
        Invoke-External "npm" @("audit", "--audit-level=high")
    }
    finally {
        Pop-Location
    }
}

function Invoke-GitHygieneChecks {
    Invoke-External "git" @("-C", $repoRoot, "diff", "--check")
    $trackedFiles = & git -C $repoRoot ls-files
    if ($LASTEXITCODE -ne 0) {
        throw "git ls-files failed."
    }

    $forbiddenFiles = foreach ($trackedFile in $trackedFiles) {
        $normalized = $trackedFile.ToLowerInvariant()
        if ($normalized -match "(^|/)\.env\.example$") {
            continue
        }
        if (
            $normalized -match "(^|/)\.env($|\.)" -or
            $normalized -match "\.(pem|key|p12|pfx|sqlite|sqlite3|patch)$" -or
            $normalized -match "probe" -or
            $normalized -match "(^|/).*(credential|token).*\.(json|ya?ml)$"
        ) {
            $trackedFile
        }
    }
    if ($forbiddenFiles) {
        throw "Tracked sensitive or temporary files are forbidden:`n$($forbiddenFiles -join "`n")"
    }
    Invoke-External "git" @("-C", $repoRoot, "status", "--short")
}

function Invoke-Actionlint {
    # actionlint
    Invoke-External "docker" @(
        "run",
        "--rm",
        "--volume",
        "${repoRoot}:/repo:ro",
        "--workdir",
        "/repo",
        $actionlintImage,
        "-color"
    )
}

function Invoke-Gitleaks {
    # gitleaks
    Invoke-External "docker" @(
        "run",
        "--rm",
        "--volume",
        "${repoRoot}:/repo:ro",
        "--workdir",
        "/repo",
        $gitleaksImage,
        "git",
        "--no-banner",
        "--redact",
        "."
    )

    $scanRoot = Join-Path $repoRoot ".tmp-gitleaks-working-tree"
    if (Test-Path -LiteralPath $scanRoot) {
        Remove-Item -LiteralPath $scanRoot -Recurse -Force
    }

    $scanFiles = & git -C $repoRoot ls-files --cached --others --exclude-standard
    if ($LASTEXITCODE -ne 0) {
        throw "git ls-files failed before Gitleaks working-tree scan."
    }

    New-Item -ItemType Directory -Path $scanRoot | Out-Null
    try {
        foreach ($scanFile in $scanFiles) {
            $scanPath = Join-Path $repoRoot $scanFile
            if (Test-Path -LiteralPath $scanPath -PathType Leaf) {
                $destination = Join-Path $scanRoot $scanFile
                $destinationParent = Split-Path -Parent $destination
                if (-not (Test-Path -LiteralPath $destinationParent)) {
                    New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
                }
                Copy-Item -LiteralPath $scanPath -Destination $destination -Force
            }
        }

        $gitleaksConfig = Join-Path $scanRoot ".gitleaks.toml"
        if (-not (Test-Path -LiteralPath $gitleaksConfig -PathType Leaf)) {
            throw "Missing .gitleaks.toml in Gitleaks working-tree scan root."
        }

        Invoke-External "docker" @(
            "run",
            "--rm",
            "--volume",
            "${scanRoot}:/scan:ro",
            "--workdir",
            "/scan",
            $gitleaksImage,
            "dir",
            "--config",
            "/scan/.gitleaks.toml",
            "--no-banner",
            "--redact",
            "."
        )
    }
    finally {
        if (Test-Path -LiteralPath $scanRoot) {
            Remove-Item -LiteralPath $scanRoot -Recurse -Force
        }
    }
}

function Invoke-DockerChecks {
    $ciEnvironment = @{
        APP_ENV = "local"
        SECURE_SSL_REDIRECT = "false"
        POSTGRES_DB = "ci_db"
        POSTGRES_USER = "ci_user"
        POSTGRES_PASSWORD = "ci-only-password"
        DJANGO_SECRET_KEY = "ci-only-secret-key-with-more-than-fifty-characters-000000"
        DJANGO_DEBUG = "false"
        DATABASE_URL = "postgresql://ci_user:ci-only-password@postgres:5432/ci_db"
        REDIS_URL = "redis://redis:6379/0"
        CELERY_BROKER_URL = "redis://redis:6379/1"
        SMS_PROVIDER = "mock"
        SMS_VERIFICATION_HMAC_KEY = "ci-only-sms-hmac-key-with-more-than-fifty-characters-000000"
        QUOTA_IDEMPOTENCY_HMAC_KEY = "ci-only-quota-hmac-key-with-more-than-fifty-characters-000000"
        GEO_DETECTION_IDEMPOTENCY_HMAC_KEY = "ci-only-geo-detection-hmac-key-with-more-than-fifty-characters-000000"
        PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY = "ci-only-plan-change-hmac-key-with-more-than-fifty-characters-000000"
        WEB_IMPORT_IDEMPOTENCY_HMAC_KEY = "ci-only-web-import-hmac-key-with-more-than-fifty-characters-000000"
        ALLOWED_HOSTS = "localhost,api"
        CSRF_TRUSTED_ORIGINS = "http://localhost:3000"
        CORS_ALLOWED_ORIGINS = "http://localhost:3000"
        NEXT_PUBLIC_APP_ENV = "local"
        NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000/api/v1"
    }
    $previousEnvironment = @{}
    $emptyEnv = New-TemporaryFile

    try {
        foreach ($entry in $ciEnvironment.GetEnumerator()) {
            $previousEnvironment[$entry.Key] = [Environment]::GetEnvironmentVariable(
                $entry.Key,
                "Process"
            )
            [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
        }
        # docker compose
        Invoke-External "docker" @(
            "compose",
            "--env-file",
            $emptyEnv.FullName,
            "--file",
            (Join-Path $repoRoot "docker-compose.yml"),
            "config",
            "--quiet"
        )
        Invoke-External "docker" @(
            "compose",
            "--env-file",
            $emptyEnv.FullName,
            "--file",
            (Join-Path $repoRoot "docker-compose.yml"),
            "build",
            "api",
            "celery",
            "celery-beat",
            "frontend"
        )
    }
    finally {
        foreach ($entry in $previousEnvironment.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
        }
        Remove-Item -LiteralPath $emptyEnv.FullName -Force
    }
}

switch ($Mode) {
    "backend" { Invoke-BackendChecks }
    "frontend" { Invoke-FrontendChecks }
    "git" { Invoke-GitHygieneChecks }
    "actionlint" { Invoke-Actionlint }
    "gitleaks" { Invoke-Gitleaks }
    "security" {
        Invoke-GitHygieneChecks
        Invoke-Actionlint
        Invoke-Gitleaks
    }
    "docker" { Invoke-DockerChecks }
    "all" {
        Invoke-BackendChecks
        Invoke-FrontendChecks
        Invoke-GitHygieneChecks
        Invoke-Actionlint
        Invoke-Gitleaks
        Invoke-DockerChecks
    }
}
