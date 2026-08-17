$ErrorActionPreference = "Stop"

function New-RandomSecret {
    ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}

function New-FernetKey {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    ([Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_"))
}

function Assert-LastExitCode([string]$Message) {
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

$env:POSTGRES_DB = "ai_credential_test_db"
$env:POSTGRES_USER = "ai_credential_test_user"
$env:POSTGRES_PASSWORD = (New-RandomSecret)
$env:DJANGO_SECRET_KEY = (New-RandomSecret)
$env:FIELD_ENCRYPTION_MASTER_KEY = (New-FernetKey)
$env:API_CREDENTIAL_ENVIRONMENT = "staging"
$env:SMS_VERIFICATION_HMAC_KEY = (New-RandomSecret)
$env:QUOTA_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:WEB_IMPORT_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:DATABASE_URL = "postgresql://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@postgres:5432/$($env:POSTGRES_DB)"
$env:REDIS_URL = "redis://redis:6379/18"
$env:CELERY_BROKER_URL = "redis://redis:6379/19"
$files = @("-f", "docker-compose.yml", "-f", "docker-compose.ai-credentials.yml")
$projectName = "xianwen-ai-credential-test"

try {
    docker compose @files --project-name $projectName --profile ai-credential-test down --volumes --remove-orphans
    Assert-LastExitCode "Initial AI credential test cleanup failed."
    docker compose @files --project-name $projectName --profile ai-credential-test build ai-credential-migrate ai-credential-tests
    Assert-LastExitCode "AI credential test images failed to build."
    docker compose @files --project-name $projectName --profile ai-credential-test up -d --wait --wait-timeout 60 postgres
    Assert-LastExitCode "AI credential PostgreSQL dependency failed to start."
    docker compose @files --project-name $projectName --profile ai-credential-test run --rm ai-credential-migrate
    Assert-LastExitCode "AI credential migrations failed."
    docker compose @files --project-name $projectName --profile ai-credential-test run --rm --no-deps ai-credential-tests
    Assert-LastExitCode "AI credential PostgreSQL tests failed."
}
finally {
    docker compose @files --project-name $projectName --profile ai-credential-test down --volumes --remove-orphans
}
