#!/usr/bin/env bash
set -euo pipefail
export QUOTA_IDEMPOTENCY_HMAC_KEY="${QUOTA_IDEMPOTENCY_HMAC_KEY:-$(openssl rand -hex 32)}"
export PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY="${PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY:-$(openssl rand -hex 32)}"

export POSTGRES_DB="${POSTGRES_DB:-risk_approval_test_db}"
export POSTGRES_USER="${POSTGRES_USER:-risk_approval_test_user}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-risk-approval-test-only-password}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-risk-approval-test-only-django-key-with-more-than-fifty-characters-000000}"
export DATABASE_URL="${DATABASE_URL:-postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}}"
export REDIS_URL="${REDIS_URL:-redis://redis:6379/0}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://redis:6379/1}"
export SMS_VERIFICATION_HMAC_KEY="${SMS_VERIFICATION_HMAC_KEY:-risk-approval-test-only-sms-hmac-key-with-more-than-fifty-characters-000000}"

cleanup() {
  docker compose --project-name xianwen-risk-approval-test --profile risk-approval-test \
    down --volumes --remove-orphans
}
trap cleanup EXIT

docker compose --project-name xianwen-risk-approval-test --profile risk-approval-test \
  run --rm --build risk-approval-tests
