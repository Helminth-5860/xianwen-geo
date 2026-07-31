#!/usr/bin/env bash
set -euo pipefail

export POSTGRES_DB="${POSTGRES_DB:-rbac_test_db}"
export POSTGRES_USER="${POSTGRES_USER:-rbac_test_user}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-rbac-test-only-password}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-rbac-test-only-django-key-with-more-than-fifty-characters-000000}"
export DATABASE_URL="${DATABASE_URL:-postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}}"
export REDIS_URL="${REDIS_URL:-redis://redis:6379/0}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://redis:6379/1}"
export SMS_VERIFICATION_HMAC_KEY="${SMS_VERIFICATION_HMAC_KEY:-rbac-test-only-sms-hmac-key-with-more-than-fifty-characters-000000}"

cleanup() {
  docker compose --project-name xianwen-rbac-test --profile rbac-test \
    down --volumes --remove-orphans
}
trap cleanup EXIT

docker compose --project-name xianwen-rbac-test --profile rbac-test \
  run --rm --build rbac-tests
