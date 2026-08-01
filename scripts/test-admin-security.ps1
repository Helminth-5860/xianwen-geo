$ErrorActionPreference = "Stop"

$defaults = @{
    POSTGRES_DB = "admin_security_test_db"
    POSTGRES_USER = "admin_security_test_user"
    POSTGRES_PASSWORD = "admin-security-test-only-password"
    DJANGO_SECRET_KEY = "admin-security-test-only-django-key-with-more-than-fifty-characters-000000"
    REDIS_URL = "redis://redis:6379/0"
    CELERY_BROKER_URL = "redis://redis:6379/1"
    SMS_VERIFICATION_HMAC_KEY = "admin-security-test-only-sms-hmac-key-with-more-than-fifty-characters-000000"
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
    docker compose --project-name xianwen-admin-security-test --profile admin-security-test run --rm --build admin-security-tests
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL/Redis administrator security tests failed."
    }
}
finally {
    docker compose --project-name xianwen-admin-security-test --profile admin-security-test down --volumes --remove-orphans
}
