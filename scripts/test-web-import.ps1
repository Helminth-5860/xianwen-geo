$ErrorActionPreference = "Stop"
function New-RandomSecret { ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")) }
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
try {
    docker compose @files --project-name xianwen-web-import-test --profile web-import-test down --volumes --remove-orphans
    docker compose @files --project-name xianwen-web-import-test --profile web-import-test up --build --attach-dependencies --abort-on-container-exit --exit-code-from web-import-tests web-import-tests
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL/Redis/web_fetch worker tests failed." }
}
finally {
    docker compose @files --project-name xianwen-web-import-test --profile web-import-test down --volumes --remove-orphans
}
