$ErrorActionPreference = "Stop"
function New-RandomSecret { ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")) }
function Assert-LastExitCode([string]$Message) {
    if ($LASTEXITCODE -ne 0) { throw $Message }
}
$env:POSTGRES_DB = "web_import_test_db"
$env:POSTGRES_USER = "web_import_test_user"
$env:POSTGRES_PASSWORD = New-RandomSecret
$env:DJANGO_SECRET_KEY = New-RandomSecret
$env:SMS_VERIFICATION_HMAC_KEY = New-RandomSecret
$env:QUOTA_IDEMPOTENCY_HMAC_KEY = New-RandomSecret
$env:PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY = New-RandomSecret
$env:WEB_IMPORT_IDEMPOTENCY_HMAC_KEY = New-RandomSecret
$env:DATABASE_URL = "postgresql://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@postgres:5432/$($env:POSTGRES_DB)"
$env:REDIS_URL = "redis://redis:6379/8"
$env:CELERY_BROKER_URL = "redis://redis:6379/9"
$files = @("-f", "docker-compose.yml", "-f", "docker-compose.web-import.yml")
$projectName = "xianwen-web-import-test"
try {
    docker compose @files --project-name $projectName --profile web-import-test down --volumes --remove-orphans
    Assert-LastExitCode "Initial web import cleanup failed."

    docker compose @files --project-name $projectName --profile web-import-test build web-import-migrate web-fetch-test-worker web-import-tests
    Assert-LastExitCode "Web import test images failed to build."

    docker compose @files --project-name $projectName --profile web-import-test up -d --wait --wait-timeout 60 postgres redis web-lab
    Assert-LastExitCode "Web import dependencies failed to start."

    docker compose @files --project-name $projectName --profile web-import-test run --rm web-import-migrate
    Assert-LastExitCode "Web import migrations failed."

    docker compose @files --project-name $projectName --profile web-import-test up -d web-fetch-test-worker
    Assert-LastExitCode "web_fetch worker failed to start."

    docker compose @files --project-name $projectName --profile web-import-test run --rm --no-deps web-import-tests
    Assert-LastExitCode "PostgreSQL/Redis/web_fetch worker tests failed."
}
finally {
    docker compose @files --project-name $projectName --profile web-import-test down --volumes --remove-orphans
}
