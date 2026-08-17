$ErrorActionPreference = "Stop"

function New-RandomSecret {
    ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}

function Assert-LastExitCode([string]$Message) {
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

$env:POSTGRES_DB = "ai_model_config_test_db"
$env:POSTGRES_USER = "ai_model_config_test_user"
$env:POSTGRES_PASSWORD = (New-RandomSecret)
$env:DJANGO_SECRET_KEY = (New-RandomSecret)
$env:SMS_VERIFICATION_HMAC_KEY = (New-RandomSecret)
$env:QUOTA_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:WEB_IMPORT_IDEMPOTENCY_HMAC_KEY = (New-RandomSecret)
$env:DATABASE_URL = "postgresql://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@postgres:5432/$($env:POSTGRES_DB)"
$env:REDIS_URL = "redis://redis:6379/16"
$env:CELERY_BROKER_URL = "redis://redis:6379/17"
$files = @("-f", "docker-compose.yml", "-f", "docker-compose.ai-model-config.yml")
$projectName = "xianwen-ai-model-config-test"

try {
    docker compose @files --project-name $projectName --profile ai-model-config-test down --volumes --remove-orphans
    Assert-LastExitCode "Initial AI model config test cleanup failed."
    docker compose @files --project-name $projectName --profile ai-model-config-test build ai-model-config-migrate ai-model-config-tests
    Assert-LastExitCode "AI model config test images failed to build."
    docker compose @files --project-name $projectName --profile ai-model-config-test up -d --wait --wait-timeout 60 postgres
    Assert-LastExitCode "AI model config PostgreSQL dependency failed to start."
    docker compose @files --project-name $projectName --profile ai-model-config-test run --rm ai-model-config-migrate
    Assert-LastExitCode "AI model config migrations failed."
    docker compose @files --project-name $projectName --profile ai-model-config-test run --rm --no-deps ai-model-config-tests
    Assert-LastExitCode "AI model config PostgreSQL tests failed."
}
finally {
    docker compose @files --project-name $projectName --profile ai-model-config-test down --volumes --remove-orphans
}
