#!/usr/bin/env bash
set -euo pipefail
random_secret() { python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
}
export POSTGRES_DB="ai_model_config_test_db"
export POSTGRES_USER="ai_model_config_test_user"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(random_secret)}"
export QUOTA_IDEMPOTENCY_HMAC_KEY="${QUOTA_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY="${PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export WEB_IMPORT_IDEMPOTENCY_HMAC_KEY="${WEB_IMPORT_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
files=(-f docker-compose.yml -f docker-compose.ai-model-config.yml)
project=xianwen-ai-model-config-test
cleanup() {
  docker compose "${files[@]}" --project-name "$project" --profile ai-model-config-test \
    down --volumes --remove-orphans || true
}
trap cleanup EXIT
cleanup
docker compose "${files[@]}" --project-name "$project" --profile ai-model-config-test \
  build ai-model-config-migrate ai-model-config-tests
docker compose "${files[@]}" --project-name "$project" --profile ai-model-config-test \
  up -d --wait --wait-timeout 60 postgres
docker compose "${files[@]}" --project-name "$project" --profile ai-model-config-test \
  run --rm ai-model-config-migrate
docker compose "${files[@]}" --project-name "$project" --profile ai-model-config-test \
  run --rm --no-deps ai-model-config-tests
