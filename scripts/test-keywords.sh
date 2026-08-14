#!/usr/bin/env bash
set -euo pipefail
random_secret() { python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
}
export POSTGRES_DB="keywords_test_db"
export POSTGRES_USER="keywords_test_user"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(random_secret)}"
export SMS_VERIFICATION_HMAC_KEY="${SMS_VERIFICATION_HMAC_KEY:-$(random_secret)}"
export QUOTA_IDEMPOTENCY_HMAC_KEY="${QUOTA_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY="${PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export WEB_IMPORT_IDEMPOTENCY_HMAC_KEY="${WEB_IMPORT_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
export REDIS_URL="${REDIS_URL:-redis://redis:6379/14}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://redis:6379/15}"
files=(-f docker-compose.yml -f docker-compose.keywords.yml)
project=xianwen-keywords-test
cleanup() {
  docker compose "${files[@]}" --project-name "$project" --profile keywords-test \
    down --volumes --remove-orphans || true
}
trap cleanup EXIT
cleanup
docker compose "${files[@]}" --project-name "$project" --profile keywords-test \
  build keyword-migrate keyword-tests
docker compose "${files[@]}" --project-name "$project" --profile keywords-test \
  up -d --wait --wait-timeout 60 postgres
docker compose "${files[@]}" --project-name "$project" --profile keywords-test \
  run --rm keyword-migrate
docker compose "${files[@]}" --project-name "$project" --profile keywords-test \
  run --rm --no-deps keyword-tests
