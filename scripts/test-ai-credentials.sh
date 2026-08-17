#!/usr/bin/env bash
set -euo pipefail
random_secret() { python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
}
fernet_key() { python - <<'PY'
import base64
import secrets
print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"))
PY
}
export POSTGRES_DB="ai_credential_test_db"
export POSTGRES_USER="ai_credential_test_user"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(random_secret)}"
export FIELD_ENCRYPTION_MASTER_KEY="${FIELD_ENCRYPTION_MASTER_KEY:-$(fernet_key)}"
export API_CREDENTIAL_ENVIRONMENT="staging"
export SMS_VERIFICATION_HMAC_KEY="${SMS_VERIFICATION_HMAC_KEY:-$(random_secret)}"
export QUOTA_IDEMPOTENCY_HMAC_KEY="${QUOTA_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY="${PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export WEB_IMPORT_IDEMPOTENCY_HMAC_KEY="${WEB_IMPORT_IDEMPOTENCY_HMAC_KEY:-$(random_secret)}"
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
export REDIS_URL="${REDIS_URL:-redis://redis:6379/18}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://redis:6379/19}"
files=(-f docker-compose.yml -f docker-compose.ai-key-management.yml)
project=xianwen-ai-credential-test
cleanup() {
  docker compose "${files[@]}" --project-name "$project" --profile ai-credential-test \
    down --volumes --remove-orphans || true
}
trap cleanup EXIT
cleanup
docker compose "${files[@]}" --project-name "$project" --profile ai-credential-test \
  build ai-credential-migrate ai-credential-tests
docker compose "${files[@]}" --project-name "$project" --profile ai-credential-test \
  up -d --wait --wait-timeout 60 postgres
docker compose "${files[@]}" --project-name "$project" --profile ai-credential-test \
  run --rm ai-credential-migrate
docker compose "${files[@]}" --project-name "$project" --profile ai-credential-test \
  run --rm --no-deps ai-credential-tests
