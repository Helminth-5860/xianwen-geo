$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($env:POSTGRES_DB)) { $env:POSTGRES_DB = "subject_schema_test_db" }
if ([string]::IsNullOrWhiteSpace($env:POSTGRES_USER)) { $env:POSTGRES_USER = "subject_schema_test_user" }
if ([string]::IsNullOrWhiteSpace($env:POSTGRES_PASSWORD)) {
    $env:POSTGRES_PASSWORD = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}
foreach ($name in @(
    "DJANGO_SECRET_KEY",
    "SMS_VERIFICATION_HMAC_KEY",
    "QUOTA_IDEMPOTENCY_HMAC_KEY",
    "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY"
)) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        [Environment]::SetEnvironmentVariable(
            $name,
            ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
        )
    }
}
if ([string]::IsNullOrWhiteSpace($env:REDIS_URL)) { $env:REDIS_URL = "redis://redis:6379/0" }
if ([string]::IsNullOrWhiteSpace($env:CELERY_BROKER_URL)) { $env:CELERY_BROKER_URL = "redis://redis:6379/1" }
if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
    $env:DATABASE_URL = "postgresql://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@postgres:5432/$($env:POSTGRES_DB)"
}
$composeFiles = @("-f", "docker-compose.yml", "-f", "docker-compose.subject-schema.yml")
docker compose @composeFiles --project-name xianwen-subject-schema-test --profile subject-schema-test down --volumes --remove-orphans
if ($LASTEXITCODE -ne 0) { throw "Unable to clean the isolated subject-schema test project." }
try {
    docker compose @composeFiles --project-name xianwen-subject-schema-test --profile subject-schema-test run --rm --build subject-schema-tests
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL/Redis subject-schema tests failed." }
}
finally {
    docker compose @composeFiles --project-name xianwen-subject-schema-test --profile subject-schema-test down --volumes --remove-orphans
}
