$ErrorActionPreference = "Stop"

function New-RandomSecret {
    ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}

function Assert-LastExitCode([string]$Message) {
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

$env:POSTGRES_DB = "keywords_test_db"
$env:POSTGRES_USER = "keywords_test_user"
$env:POSTGRES_PASSWORD = (New-RandomSecret)
$env:DJANGO_SECRET_KEY = (New-RandomSecret)
$env:SMS_VERIFICATION_HMAC_KEY = (New-RandomSecret)
$env:QUOTA_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:WEB_IMPORT_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:DATABASE_URL = "postgresql://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@postgres:5432/$($env:POSTGRES_DB)"
$env:REDIS_URL = "redis://redis:6379/14"
$env:CELERY_BROKER_URL = "redis://redis:6379/15"
$files = @("-f", "docker-compose.yml", "-f", "docker-compose.keywords.yml")
$projectName = "xianwen-keywords-test"

try {
    docker compose @files --project-name $projectName --profile keywords-test down --volumes --remove-orphans
    Assert-LastExitCode "Initial keyword test cleanup failed."
    docker compose @files --project-name $projectName --profile keywords-test build keyword-migrate keyword-tests
    Assert-LastExitCode "Keyword test images failed to build."
    docker compose @files --project-name $projectName --profile keywords-test up -d --wait --wait-timeout 60 postgres
    Assert-LastExitCode "Keyword PostgreSQL dependency failed to start."
    docker compose @files --project-name $projectName --profile keywords-test run --rm keyword-migrate
    Assert-LastExitCode "Keyword migrations failed."
    docker compose @files --project-name $projectName --profile keywords-test run --rm --no-deps keyword-tests
    Assert-LastExitCode "Keyword PostgreSQL tests failed."
}
finally {
    docker compose @files --project-name $projectName --profile keywords-test down --volumes --remove-orphans
}
