$ErrorActionPreference = "Stop"

function New-RandomSecret {
    ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}

function Assert-LastExitCode([string]$Message) {
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

$env:POSTGRES_DB = "questions_test_db"
$env:POSTGRES_USER = "questions_test_user"
$env:POSTGRES_PASSWORD = (New-RandomSecret)
$env:DJANGO_SECRET_KEY = (New-RandomSecret)
$env:SMS_VERIFICATION_HMAC_KEY = (New-RandomSecret)
$env:QUOTA_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:WEB_IMPORT_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:DATABASE_URL = "postgresql://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@postgres:5432/$($env:POSTGRES_DB)"
$env:REDIS_URL = "redis://redis:6379/12"
$env:CELERY_BROKER_URL = "redis://redis:6379/13"
$files = @("-f", "docker-compose.yml", "-f", "docker-compose.questions.yml")
$projectName = "xianwen-questions-test"

try {
    docker compose @files --project-name $projectName --profile questions-test down --volumes --remove-orphans
    Assert-LastExitCode "Initial question catalog test cleanup failed."
    docker compose @files --project-name $projectName --profile questions-test build question-migrate question-tests
    Assert-LastExitCode "Question catalog test images failed to build."
    docker compose @files --project-name $projectName --profile questions-test up -d --wait --wait-timeout 60 postgres
    Assert-LastExitCode "Question catalog PostgreSQL dependency failed to start."
    docker compose @files --project-name $projectName --profile questions-test run --rm question-migrate
    Assert-LastExitCode "Question catalog migrations failed."
    docker compose @files --project-name $projectName --profile questions-test run --rm --no-deps question-tests
    Assert-LastExitCode "Question catalog PostgreSQL tests failed."
}
finally {
    docker compose @files --project-name $projectName --profile questions-test down --volumes --remove-orphans
}
