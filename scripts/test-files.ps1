$ErrorActionPreference = "Stop"
function New-RandomSecret { ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")) }
if ([string]::IsNullOrWhiteSpace($env:POSTGRES_DB)) { $env:POSTGRES_DB = "file_test_db" }
if ([string]::IsNullOrWhiteSpace($env:POSTGRES_USER)) { $env:POSTGRES_USER = "file_test_user" }
foreach ($name in @("POSTGRES_PASSWORD", "DJANGO_SECRET_KEY", "SMS_VERIFICATION_HMAC_KEY", "QUOTA_IDEMPOTENCY_HMAC_KEY", "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY", "FILE_IDEMPOTENCY_HMAC_KEY", "S3_SECRET_KEY")) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        [Environment]::SetEnvironmentVariable($name, (New-RandomSecret))
    }
}
if ([string]::IsNullOrWhiteSpace($env:S3_ACCESS_KEY)) { $env:S3_ACCESS_KEY = "minio$([guid]::NewGuid().ToString('N').Substring(0, 12))" }
if ([string]::IsNullOrWhiteSpace($env:S3_BUCKET)) { $env:S3_BUCKET = "xianwen-files-test" }
if ([string]::IsNullOrWhiteSpace($env:REDIS_URL)) { $env:REDIS_URL = "redis://redis:6379/0" }
if ([string]::IsNullOrWhiteSpace($env:CELERY_BROKER_URL)) { $env:CELERY_BROKER_URL = "redis://redis:6379/1" }
if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) { $env:DATABASE_URL = "postgresql://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@postgres:5432/$($env:POSTGRES_DB)" }
$files = @("-f", "docker-compose.yml", "-f", "docker-compose.files.yml")
docker compose @files --project-name xianwen-file-test --profile file-test down --volumes --remove-orphans
if ($LASTEXITCODE -ne 0) { throw "Unable to clean isolated file test project." }
try {
    docker compose @files --project-name xianwen-file-test --profile file-test run --rm --build file-tests
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL/Redis/MinIO file tests failed." }
}
finally {
    docker compose @files --project-name xianwen-file-test --profile file-test down --volumes --remove-orphans
}
