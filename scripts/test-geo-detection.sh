#!/usr/bin/env bash
set -euo pipefail
random_secret() { python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
}
export POSTGRES_DB="geo_detection_test_db"
export POSTGRES_USER="geo_detection_test_user"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(random_secret)}"
export SMS_VERIFICATION_HMAC_KEY="${SMS_VERIFICATION_HMAC_KEY:-$(random_secret)}"
export QUOTA_IDEMPOTENCY_HMAC_KEY="${QUOTA_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export GEO_DETECTION_IDEMPOTENCY_HMAC_KEY="${GEO_DETECTION_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY="${PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export WEB_IMPORT_IDEMPOTENCY_HMAC_KEY="${WEB_IMPORT_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY="${QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
export REDIS_URL="redis://redis:6379/20"
export CELERY_BROKER_URL="redis://redis:6379/21"
files=(-f docker-compose.yml -f docker-compose.geo-detection.yml)
project=xianwen-geo-detection-test
cleanup() {
  docker compose "${files[@]}" --project-name "$project" --profile geo-detection-test \
    down --volumes --remove-orphans || true
}
trap cleanup EXIT
cleanup
docker compose "${files[@]}" --project-name "$project" --profile geo-detection-test \
  build geo-detection-migrate geo-detection-tests
docker compose "${files[@]}" --project-name "$project" --profile geo-detection-test \
  up -d --wait --wait-timeout 60 postgres redis
docker compose "${files[@]}" --project-name "$project" --profile geo-detection-test \
  run --rm geo-detection-migrate
docker compose "${files[@]}" --project-name "$project" --profile geo-detection-test \
  run --rm --no-deps geo-detection-tests
