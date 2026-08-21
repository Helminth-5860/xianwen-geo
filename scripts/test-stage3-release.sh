#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export POSTGRES_DB=stage3_release_test_db POSTGRES_USER=stage3_release_test_user
export POSTGRES_PASSWORD="$(openssl rand -hex 32)" DJANGO_SECRET_KEY="$(openssl rand -hex 32)"
export SMS_VERIFICATION_HMAC_KEY="$(openssl rand -hex 32)" QUOTA_IDEMPOTENCY_HMAC_KEY="$(openssl rand -hex 32)"
export GEO_DETECTION_IDEMPOTENCY_HMAC_KEY="$(openssl rand -hex 32)" PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY="$(openssl rand -hex 32)"
export WEB_IMPORT_IDEMPOTENCY_HMAC_KEY="$(openssl rand -hex 32)" QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY="$(openssl rand -hex 32)"
export ARTICLE_IDEMPOTENCY_HMAC_KEY="$(openssl rand -hex 32)" IMAGE_IDEMPOTENCY_HMAC_KEY="$(openssl rand -hex 32)"
export REPORT_SHARE_HMAC_KEY="$(openssl rand -hex 32)"
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
export REDIS_URL=redis://redis:6379/12 CELERY_BROKER_URL=redis://redis:6379/13
files=(-f "$repo/docker-compose.yml" -f "$repo/docker-compose.stage3-release.yml")
project=xianwen-stage3-release-test
cleanup() { docker compose "${files[@]}" --project-name "$project" --profile stage3-release-test down --volumes --remove-orphans; }
trap cleanup EXIT
cleanup
docker compose "${files[@]}" --project-name "$project" --profile stage3-release-test build stage3-release-migrate stage3-release-tests
docker compose "${files[@]}" --project-name "$project" --profile stage3-release-test up -d --wait --wait-timeout 60 postgres redis
docker compose "${files[@]}" --project-name "$project" --profile stage3-release-test run --rm stage3-release-migrate
docker compose "${files[@]}" --project-name "$project" --profile stage3-release-test run --rm --no-deps stage3-release-tests
