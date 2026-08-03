#!/usr/bin/env bash
set -euo pipefail
random_secret() { openssl rand -hex 32; }
export POSTGRES_DB="${POSTGRES_DB:-quota_test_db}"
export POSTGRES_USER="${POSTGRES_USER:-quota_test_user}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(random_secret)}"
export SMS_VERIFICATION_HMAC_KEY="${SMS_VERIFICATION_HMAC_KEY:-$(random_secret)}"
export QUOTA_IDEMPOTENCY_HMAC_KEY="${QUOTA_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY="${PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export DATABASE_URL="${DATABASE_URL:-postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}}"
export REDIS_URL="${REDIS_URL:-redis://redis:6379/0}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://redis:6379/1}"
cleanup() {
  docker compose --project-name xianwen-quota-test --profile quota-test \
    down --volumes --remove-orphans
}
trap cleanup EXIT
docker compose --project-name xianwen-quota-test --profile quota-test \
  run --rm --build quota-tests
