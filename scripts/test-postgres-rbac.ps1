$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($env:QUOTA_IDEMPOTENCY_HMAC_KEY)) {
    $env:QUOTA_IDEMPOTENCY_HMAC_KEY = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}
if ([string]::IsNullOrWhiteSpace($env:PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY)) {
    $env:PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}
if ([string]::IsNullOrWhiteSpace($env:WEB_IMPORT_IDEMPOTENCY_HMAC_KEY)) {
    $env:WEB_IMPORT_IDEMPOTENCY_HMAC_KEY = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}

$defaults = @{
    POSTGRES_DB = "rbac_test_db"
    POSTGRES_USER = "rbac_test_user"
    POSTGRES_PASSWORD = "rbac-test-only-password"
    DJANGO_SECRET_KEY = "rbac-test-only-django-key-with-more-than-fifty-characters-000000"
    REDIS_URL = "redis://redis:6379/0"
    CELERY_BROKER_URL = "redis://redis:6379/1"
    SMS_VERIFICATION_HMAC_KEY = "rbac-test-only-sms-hmac-key-with-more-than-fifty-characters-000000"
}
foreach ($item in $defaults.GetEnumerator()) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($item.Key))) {
        [Environment]::SetEnvironmentVariable($item.Key, $item.Value)
    }
}
if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
    $env:DATABASE_URL = "postgresql://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@postgres:5432/$($env:POSTGRES_DB)"
}

try {
    docker compose --project-name xianwen-rbac-test --profile rbac-test run --rm --build rbac-tests
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL RBAC concurrency tests failed."
    }
}
finally {
    docker compose --project-name xianwen-rbac-test --profile rbac-test down --volumes --remove-orphans
}
