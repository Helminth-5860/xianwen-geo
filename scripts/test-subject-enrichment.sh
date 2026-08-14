#!/usr/bin/env bash
set -euo pipefail
random_secret() { python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
}
export POSTGRES_DB="subject_enrichment_test_db"
export POSTGRES_USER="subject_enrichment_test_user"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(random_secret)}"
for name in SMS_VERIFICATION_HMAC_KEY QUOTA_IDEMPOTENCY_HMAC_KEY PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY FILE_IDEMPOTENCY_HMAC_KEY WEB_IMPORT_IDEMPOTENCY_HMAC_KEY SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY; do
  if [[ -z "${!name:-}" ]]; then export "$name=$(random_secret)"; fi
done
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
export REDIS_URL="redis://redis:6379/10"
export CELERY_BROKER_URL="redis://redis:6379/11"
files=(-f docker-compose.yml -f docker-compose.subject-enrichment.yml)
project=xianwen-subject-enrichment-test
cleanup() { docker compose "${files[@]}" --project-name "$project" --profile subject-enrichment-test down --volumes --remove-orphans || true; }
trap cleanup EXIT
cleanup
docker compose "${files[@]}" --project-name "$project" --profile subject-enrichment-test build subject-enrichment-migrate subject-enrichment-worker subject-enrichment-tests
docker compose "${files[@]}" --project-name "$project" --profile subject-enrichment-test up -d --wait --wait-timeout 60 postgres redis
docker compose "${files[@]}" --project-name "$project" --profile subject-enrichment-test run --rm subject-enrichment-migrate
docker compose "${files[@]}" --project-name "$project" --profile subject-enrichment-test up -d subject-enrichment-worker
docker compose "${files[@]}" --project-name "$project" --profile subject-enrichment-test run --rm --no-deps subject-enrichment-tests
