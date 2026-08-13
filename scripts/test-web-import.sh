#!/usr/bin/env bash
set -euo pipefail
random_secret() { openssl rand -hex 32; }
export POSTGRES_DB="web_import_test_db"
export POSTGRES_USER="web_import_test_user"
export POSTGRES_PASSWORD="$(random_secret)"
export DJANGO_SECRET_KEY="$(random_secret)"
export SMS_VERIFICATION_HMAC_KEY="$(random_secret)"
export QUOTA_IDEMPOTENCY_HMAC_KEY="$(random_secret)"
export PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY="$(random_secret)"
export WEB_IMPORT_IDEMPOTENCY_HMAC_KEY="$(random_secret)"
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
export REDIS_URL="redis://redis:6379/8"
export CELERY_BROKER_URL="redis://redis:6379/9"
compose=(docker compose -f docker-compose.yml -f docker-compose.web-import.yml)
cleanup() {
  "${compose[@]}" --project-name xianwen-web-import-test --profile web-import-test down --volumes --remove-orphans
}
trap cleanup EXIT
cleanup
"${compose[@]}" --project-name xianwen-web-import-test --profile web-import-test up --build --attach-dependencies --abort-on-container-exit --exit-code-from web-import-tests web-import-tests
