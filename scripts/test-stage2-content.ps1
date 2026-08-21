$ErrorActionPreference = "Stop"

function New-RandomSecret {
    ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}

function Assert-LastExitCode([string]$Message) {
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

$env:POSTGRES_DB = "stage2_content_test_db"
$env:POSTGRES_USER = "stage2_content_test_user"
$env:POSTGRES_PASSWORD = (New-RandomSecret)
$env:DJANGO_SECRET_KEY = (New-RandomSecret)
$env:SMS_VERIFICATION_HMAC_KEY = (New-RandomSecret)
$env:QUOTA_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:GEO_DETECTION_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:WEB_IMPORT_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:ARTICLE_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:IMAGE_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:REPORT_SHARE_HMAC_KEY = (New-RandomSecret)
$env:DATABASE_URL = "postgresql://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@postgres:5432/$($env:POSTGRES_DB)"
$env:REDIS_URL = "redis://redis:6379/22"
$env:CELERY_BROKER_URL = "redis://redis:6379/23"
$files = @("-f", "docker-compose.yml", "-f", "docker-compose.stage2-content.yml")
$projectName = "xianwen-stage2-content-test"

try {
    docker compose @files --project-name $projectName --profile stage2-content-test down --volumes --remove-orphans
    Assert-LastExitCode "Initial Stage 2 content test cleanup failed."
    docker compose @files --project-name $projectName --profile stage2-content-test build stage2-content-migrate stage2-content-tests
    Assert-LastExitCode "Stage 2 content test images failed to build."
    docker compose @files --project-name $projectName --profile stage2-content-test up -d --wait --wait-timeout 60 postgres redis
    Assert-LastExitCode "Stage 2 PostgreSQL/Redis dependencies failed to start."
    docker compose @files --project-name $projectName --profile stage2-content-test run --rm stage2-content-migrate
    Assert-LastExitCode "Stage 2 content migrations failed."
    docker compose @files --project-name $projectName --profile stage2-content-test run --rm --no-deps stage2-content-tests
    Assert-LastExitCode "Stage 2 content PostgreSQL tests failed."
}
finally {
    docker compose @files --project-name $projectName --profile stage2-content-test down --volumes --remove-orphans
}
