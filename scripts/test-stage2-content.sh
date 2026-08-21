#!/usr/bin/env bash
set -euo pipefail
random_secret() { python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
}
export POSTGRES_DB="stage2_content_test_db"
export POSTGRES_USER="stage2_content_test_user"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(random_secret)}"
export SMS_VERIFICATION_HMAC_KEY="${SMS_VERIFICATION_HMAC_KEY:-$(random_secret)}"
export QUOTA_IDEMPOTENCY_HMAC_KEY="${QUOTA_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export GEO_DETECTION_IDEMPOTENCY_HMAC_KEY="${GEO_DETECTION_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY="${PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export WEB_IMPORT_IDEMPOTENCY_HMAC_KEY="${WEB_IMPORT_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY="${QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export ARTICLE_IDEMPOTENCY_HMAC_KEY="${ARTICLE_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export REPORT_SHARE_HMAC_KEY="${REPORT_SHARE_HMAC_KEY:-$(random_secret)}"
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
export REDIS_URL="redis://redis:6379/22"
export CELERY_BROKER_URL="redis://redis:6379/23"
files=(-f docker-compose.yml -f docker-compose.stage2-content.yml)
project=xianwen-stage2-content-test
cleanup() {
  docker compose "${files[@]}" --project-name "$project" --profile stage2-content-test \
    down --volumes --remove-orphans || true
}
trap cleanup EXIT
cleanup
docker compose "${files[@]}" --project-name "$project" --profile stage2-content-test \
  build stage2-content-migrate stage2-content-tests
docker compose "${files[@]}" --project-name "$project" --profile stage2-content-test \
  up -d --wait --wait-timeout 60 postgres redis
docker compose "${files[@]}" --project-name "$project" --profile stage2-content-test \
  run --rm stage2-content-migrate
docker compose "${files[@]}" --project-name "$project" --profile stage2-content-test \
  run --rm --no-deps stage2-content-tests
