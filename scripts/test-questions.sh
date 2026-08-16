#!/usr/bin/env bash
set -euo pipefail
random_secret() { python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
}
export POSTGRES_DB="questions_test_db"
export POSTGRES_USER="questions_test_user"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(random_secret)}"
export SMS_VERIFICATION_HMAC_KEY="${SMS_VERIFICATION_HMAC_KEY:-$(random_secret)}"
export QUOTA_IDEMPOTENCY_HMAC_KEY="${QUOTA_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY="${PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export WEB_IMPORT_IDEMPOTENCY_HMAC_KEY="${WEB_IMPORT_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY="${QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
export REDIS_URL="${REDIS_URL:-redis://redis:6379/12}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://redis:6379/13}"
files=(-f docker-compose.yml -f docker-compose.questions.yml)
project=xianwen-questions-test
cleanup() {
  docker compose "${files[@]}" --project-name "$project" --profile questions-test \
    down --volumes --remove-orphans || true
}
trap cleanup EXIT
cleanup
docker compose "${files[@]}" --project-name "$project" --profile questions-test \
  build question-migrate question-tests
docker compose "${files[@]}" --project-name "$project" --profile questions-test \
  up -d --wait --wait-timeout 60 postgres
docker compose "${files[@]}" --project-name "$project" --profile questions-test \
  run --rm question-migrate
docker compose "${files[@]}" --project-name "$project" --profile questions-test \
  run --rm --no-deps question-tests
