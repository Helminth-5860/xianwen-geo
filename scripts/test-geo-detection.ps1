$ErrorActionPreference = "Stop"

function New-RandomSecret {
    ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}

function Assert-LastExitCode([string]$Message) {
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

$env:POSTGRES_DB = "geo_detection_test_db"
$env:POSTGRES_USER = "geo_detection_test_user"
$env:POSTGRES_PASSWORD = (New-RandomSecret)
$env:DJANGO_SECRET_KEY = (New-RandomSecret)
$env:SMS_VERIFICATION_HMAC_KEY = (New-RandomSecret)
$env:QUOTA_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:GEO_DETECTION_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:WEB_IMPORT_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:DATABASE_URL = "postgresql://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@postgres:5432/$($env:POSTGRES_DB)"
$env:REDIS_URL = "redis://redis:6379/20"
$env:CELERY_BROKER_URL = "redis://redis:6379/21"
$files = @("-f", "docker-compose.yml", "-f", "docker-compose.geo-detection.yml")
$projectName = "xianwen-geo-detection-test"

try {
    docker compose @files --project-name $projectName --profile geo-detection-test down --volumes --remove-orphans
    Assert-LastExitCode "Initial GEO detection test cleanup failed."
    docker compose @files --project-name $projectName --profile geo-detection-test build geo-detection-migrate geo-detection-tests
    Assert-LastExitCode "GEO detection test images failed to build."
    docker compose @files --project-name $projectName --profile geo-detection-test up -d --wait --wait-timeout 60 postgres redis
    Assert-LastExitCode "GEO detection PostgreSQL/Redis dependencies failed to start."
    docker compose @files --project-name $projectName --profile geo-detection-test run --rm geo-detection-migrate
    Assert-LastExitCode "GEO detection migrations failed."
    docker compose @files --project-name $projectName --profile geo-detection-test run --rm --no-deps geo-detection-tests
    Assert-LastExitCode "GEO detection PostgreSQL/Redis tests failed."
}
finally {
    docker compose @files --project-name $projectName --profile geo-detection-test down --volumes --remove-orphans
}
