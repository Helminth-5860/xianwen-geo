#!/usr/bin/env bash
set -euo pipefail
export QUOTA_IDEMPOTENCY_HMAC_KEY="${QUOTA_IDEMPOTENCY_HMAC_KEY:-$(openssl rand -hex 32)}"
random_secret() { openssl rand -hex 32; }
export POSTGRES_DB="${POSTGRES_DB:-subscription_test_db}"
export POSTGRES_USER="${POSTGRES_USER:-subscription_test_user}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(random_secret)}"
export SMS_VERIFICATION_HMAC_KEY="${SMS_VERIFICATION_HMAC_KEY:-$(random_secret)}"
export DATABASE_URL="${DATABASE_URL:-postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}}"
export REDIS_URL="${REDIS_URL:-redis://redis:6379/0}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://redis:6379/1}"
cleanup() {
  docker compose --project-name xianwen-subscription-test --profile subscription-test \
    down --volumes --remove-orphans
}
trap cleanup EXIT
docker compose --project-name xianwen-subscription-test --profile subscription-test \
  run --rm --build subscription-tests
