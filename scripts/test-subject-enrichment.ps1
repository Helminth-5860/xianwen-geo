$ErrorActionPreference = "Stop"

function New-RandomSecret {
    ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}

function Assert-LastExitCode([string]$Message) {
    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

$env:POSTGRES_DB = "subject_enrichment_test_db"
$env:POSTGRES_USER = "subject_enrichment_test_user"
$env:POSTGRES_PASSWORD = (New-RandomSecret)
$env:DJANGO_SECRET_KEY = (New-RandomSecret)

foreach ($name in @(
    "SMS_VERIFICATION_HMAC_KEY",
    "QUOTA_IDEMPOTENCY_HMAC_KEY",
    "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY",
    "FILE_IDEMPOTENCY_HMAC_KEY",
    "WEB_IMPORT_IDEMPOTENCY_HMAC_KEY",
    "SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY"
)) {
    Set-Item -Path "Env:$name" -Value (New-RandomSecret)
}

$env:DATABASE_URL = "postgresql://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@postgres:5432/$($env:POSTGRES_DB)"
$env:REDIS_URL = "redis://redis:6379/10"
$env:CELERY_BROKER_URL = "redis://redis:6379/11"

$files = @(
    "-f", "docker-compose.yml",
    "-f", "docker-compose.subject-enrichment.yml"
)
$projectName = "xianwen-subject-enrichment-test"

try {
    docker compose @files --project-name $projectName --profile subject-enrichment-test down --volumes --remove-orphans
    Assert-LastExitCode "Initial subject enrichment cleanup failed."

    docker compose @files --project-name $projectName --profile subject-enrichment-test build subject-enrichment-migrate subject-enrichment-worker subject-enrichment-tests
    Assert-LastExitCode "Subject enrichment test images failed to build."

    docker compose @files --project-name $projectName --profile subject-enrichment-test up -d --wait --wait-timeout 60 postgres redis
    Assert-LastExitCode "Subject enrichment dependencies failed to start."

    docker compose @files --project-name $projectName --profile subject-enrichment-test run --rm subject-enrichment-migrate
    Assert-LastExitCode "Subject enrichment migrations failed."

    docker compose @files --project-name $projectName --profile subject-enrichment-test up -d subject-enrichment-worker
    Assert-LastExitCode "ai_content worker failed to start."

    docker compose @files --project-name $projectName --profile subject-enrichment-test run --rm --no-deps subject-enrichment-tests
    Assert-LastExitCode "PostgreSQL/Redis/ai_content worker tests failed."
}
finally {
    docker compose @files --project-name $projectName --profile subject-enrichment-test down --volumes --remove-orphans
}
