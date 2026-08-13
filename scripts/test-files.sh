#!/usr/bin/env bash
set -euo pipefail
random_secret() { openssl rand -hex 32; }
export APP_ENV="local"
export POSTGRES_DB="${POSTGRES_DB:-file_test_db}"
export POSTGRES_USER="${POSTGRES_USER:-file_test_user}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(random_secret)}"
export SMS_VERIFICATION_HMAC_KEY="${SMS_VERIFICATION_HMAC_KEY:-$(random_secret)}"
export QUOTA_IDEMPOTENCY_HMAC_KEY="${QUOTA_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY="${PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export FILE_IDEMPOTENCY_HMAC_KEY="${FILE_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export S3_ACCESS_KEY="${S3_ACCESS_KEY:-minio$(openssl rand -hex 8)}"
export S3_SECRET_KEY="${S3_SECRET_KEY:-$(random_secret)}"
export S3_BUCKET="${S3_BUCKET:-xianwen-files-test}"
export DATABASE_URL="${DATABASE_URL:-postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}}"
export FILE_PROCESSING_DATABASE_URL="${FILE_PROCESSING_DATABASE_URL:-postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/test_${POSTGRES_DB}}"
export REDIS_URL="${REDIS_URL:-redis://redis:6379/0}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://redis:6379/1}"
compose=(docker compose -f docker-compose.yml -f docker-compose.files.yml)
cleanup() {
  "${compose[@]}" --project-name xianwen-file-test --profile file-test down --volumes --remove-orphans
}
trap cleanup EXIT
cleanup
"${compose[@]}" --project-name xianwen-file-test --profile file-test run --rm --build file-tests
