$ErrorActionPreference = 'Stop'

function New-RandomSecret { [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N') }
function Assert-LastExitCode([string]$Message) { if ($LASTEXITCODE -ne 0) { throw $Message } }

$env:POSTGRES_DB = 'stage3_release_test_db'
$env:POSTGRES_USER = 'stage3_release_test_user'
$env:POSTGRES_PASSWORD = New-RandomSecret
$env:DJANGO_SECRET_KEY = New-RandomSecret
$env:SMS_VERIFICATION_HMAC_KEY = New-RandomSecret
$env:QUOTA_IDEMPOTENCY_HMAC_KEY = New-RandomSecret
$env:GEO_DETECTION_IDEMPOTENCY_HMAC_KEY = New-RandomSecret
$env:PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY = New-RandomSecret
$env:WEB_IMPORT_IDEMPOTENCY_HMAC_KEY = New-RandomSecret
$env:QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY = New-RandomSecret
$env:ARTICLE_IDEMPOTENCY_HMAC_KEY = New-RandomSecret
$env:IMAGE_IDEMPOTENCY_HMAC_KEY = New-RandomSecret
$env:VIDEO_IDEMPOTENCY_HMAC_KEY = New-RandomSecret
$env:REPORT_SHARE_HMAC_KEY = New-RandomSecret
$env:DATABASE_URL = "postgresql://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@postgres:5432/$($env:POSTGRES_DB)"
$env:REDIS_URL = 'redis://redis:6379/12'
$env:CELERY_BROKER_URL = 'redis://redis:6379/13'
$files = @('-f', 'docker-compose.yml', '-f', 'docker-compose.stage3-release.yml')
$projectName = 'xianwen-stage3-release-test'

try {
    docker compose @files --project-name $projectName --profile stage3-release-test down --volumes --remove-orphans
    Assert-LastExitCode 'Initial Stage 3 release test cleanup failed.'
    docker compose @files --project-name $projectName --profile stage3-release-test build stage3-release-migrate stage3-release-tests
    Assert-LastExitCode 'Stage 3 release test images failed to build.'
    docker compose @files --project-name $projectName --profile stage3-release-test up -d --wait --wait-timeout 60 postgres redis
    Assert-LastExitCode 'Stage 3 PostgreSQL/Redis dependencies failed to start.'
    docker compose @files --project-name $projectName --profile stage3-release-test run --rm stage3-release-migrate
    Assert-LastExitCode 'Stage 3 release migrations failed.'
    docker compose @files --project-name $projectName --profile stage3-release-test run --rm --no-deps stage3-release-tests
    Assert-LastExitCode 'Stage 3 PostgreSQL/Redis tests failed.'
}
finally {
    docker compose @files --project-name $projectName --profile stage3-release-test down --volumes --remove-orphans
}
