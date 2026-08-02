$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($env:QUOTA_IDEMPOTENCY_HMAC_KEY)) {
    $env:QUOTA_IDEMPOTENCY_HMAC_KEY = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}
if ([string]::IsNullOrWhiteSpace($env:POSTGRES_DB)) { $env:POSTGRES_DB = "subscription_test_db" }
if ([string]::IsNullOrWhiteSpace($env:POSTGRES_USER)) { $env:POSTGRES_USER = "subscription_test_user" }
if ([string]::IsNullOrWhiteSpace($env:POSTGRES_PASSWORD)) {
    $env:POSTGRES_PASSWORD = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}
if ([string]::IsNullOrWhiteSpace($env:DJANGO_SECRET_KEY)) {
    $env:DJANGO_SECRET_KEY = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}
if ([string]::IsNullOrWhiteSpace($env:SMS_VERIFICATION_HMAC_KEY)) {
    $env:SMS_VERIFICATION_HMAC_KEY = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}
if ([string]::IsNullOrWhiteSpace($env:REDIS_URL)) { $env:REDIS_URL = "redis://redis:6379/0" }
if ([string]::IsNullOrWhiteSpace($env:CELERY_BROKER_URL)) { $env:CELERY_BROKER_URL = "redis://redis:6379/1" }
if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
    $env:DATABASE_URL = "postgresql://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@postgres:5432/$($env:POSTGRES_DB)"
}
try {
    docker compose --project-name xianwen-subscription-test --profile subscription-test run --rm --build subscription-tests
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL subscription tests failed." }
}
finally { docker compose --project-name xianwen-subscription-test --profile subscription-test down --volumes --remove-orphans }
