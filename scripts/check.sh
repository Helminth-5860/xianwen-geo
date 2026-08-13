#!/usr/bin/env bash
set -euo pipefail

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly MODE="${1:-all}"
readonly ACTIONLINT_IMAGE="rhysd/actionlint:1.7.12"
readonly GITLEAKS_IMAGE="zricethezav/gitleaks:v8.30.1"

case "$MODE" in
  all|backend|frontend|git|security|actionlint|gitleaks|docker) ;;
  *)
    echo "Usage: $0 [all|backend|frontend|git|security|actionlint|gitleaks|docker]" >&2
    exit 2
    ;;
esac

backend_python() {
  if [[ -x "$REPO_ROOT/backend/.venv/bin/python" ]]; then
    printf '%s\n' "$REPO_ROOT/backend/.venv/bin/python"
  elif [[ -x "$REPO_ROOT/backend/.venv/Scripts/python.exe" ]]; then
    printf '%s\n' "$REPO_ROOT/backend/.venv/Scripts/python.exe"
  else
    command -v python3 || command -v python
  fi
}

check_backend() {
  local python_bin
  python_bin="$(backend_python)"
  "$python_bin" -c \
    'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 is required"'
  (
    cd "$REPO_ROOT/backend"
    "$python_bin" -m ruff check .
    "$python_bin" -m ruff format --check .
    "$python_bin" -m mypy
    DJANGO_SETTINGS_MODULE=config.django_settings.test "$python_bin" manage.py check
    DJANGO_SETTINGS_MODULE=config.django_settings.test \
      "$python_bin" manage.py makemigrations --check --dry-run
    "$python_bin" -m pytest
    "$python_bin" -m openapi_spec_validator ../openapi/openapi-v1.yaml
    "$python_bin" -m pip_audit -r requirements-dev.txt
  )
}

check_frontend() {
  local expected_node actual_node
  expected_node="v$(tr -d '\r\n' < "$REPO_ROOT/frontend/.nvmrc")"
  actual_node="$(node --version)"
  if [[ "$actual_node" != "$expected_node" ]]; then
    echo "Expected Node.js $expected_node, got $actual_node." >&2
    exit 1
  fi
  (
    cd "$REPO_ROOT/frontend"
    npm run lint
    npm run format:check
    npm run typecheck
    npm test
    npm run build
    npm audit --audit-level=high
  )
}

check_git_hygiene() {
  local tracked_file normalized bad_files=""
  git -C "$REPO_ROOT" diff --check
  while IFS= read -r tracked_file; do
    normalized="${tracked_file,,}"
    case "$normalized" in
      .env.example|*/.env.example) ;;
      .env|*/.env|.env.*|*/.env.*|*.pem|*.key|*.p12|*.pfx|*.sqlite|*.sqlite3|*.patch|*probe*|*credentials*.json|*credentials*.yaml|*credentials*.yml|*token*.json|*token*.yaml|*token*.yml)
        bad_files+="${tracked_file}"$'\n'
        ;;
    esac
  done < <(git -C "$REPO_ROOT" ls-files)
  if [[ -n "$bad_files" ]]; then
    echo "Tracked sensitive or temporary files are forbidden:" >&2
    printf '%s' "$bad_files" >&2
    exit 1
  fi
  git -C "$REPO_ROOT" status --short
}

check_actionlint() {
  docker run --rm \
    --volume "$REPO_ROOT:/repo:ro" \
    --workdir /repo \
    "$ACTIONLINT_IMAGE" -color
}

check_gitleaks() {
  docker run --rm \
    --volume "$REPO_ROOT:/repo:ro" \
    --workdir /repo \
    "$GITLEAKS_IMAGE" git --no-banner --redact .
  git -C "$REPO_ROOT" ls-files --cached --others --exclude-standard -z |
    while IFS= read -r -d '' tracked_file; do
      if [[ -f "$REPO_ROOT/$tracked_file" ]]; then
        printf '\nFILE:%s\n' "$tracked_file"
        cat "$REPO_ROOT/$tracked_file"
      fi
    done | docker run --rm --interactive "$GITLEAKS_IMAGE" stdin --no-banner --redact
}

check_docker() {
  local empty_env
  empty_env="$(mktemp)"
  trap 'rm -f "$empty_env"' RETURN
  env \
    APP_ENV=local \
    SECURE_SSL_REDIRECT=false \
    POSTGRES_DB=ci_db \
    POSTGRES_USER=ci_user \
    POSTGRES_PASSWORD=ci-only-password \
    DJANGO_SECRET_KEY=ci-only-secret-key-with-more-than-fifty-characters-000000 \
    DJANGO_DEBUG=false \
    DATABASE_URL=postgresql://ci_user:ci-only-password@postgres:5432/ci_db \
    REDIS_URL=redis://redis:6379/0 \
    CELERY_BROKER_URL=redis://redis:6379/1 \
    SMS_PROVIDER=mock \
    SMS_VERIFICATION_HMAC_KEY=ci-only-sms-hmac-key-with-more-than-fifty-characters-000000 \
    QUOTA_IDEMPOTENCY_HMAC_KEY=ci-only-quota-hmac-key-with-more-than-fifty-characters-000000 \
    PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY=ci-only-plan-change-hmac-key-with-more-than-fifty-characters-000000 \
    WEB_IMPORT_IDEMPOTENCY_HMAC_KEY=ci-only-web-import-hmac-key-with-more-than-fifty-characters-000000 \
    ALLOWED_HOSTS=localhost,api \
    CSRF_TRUSTED_ORIGINS=http://localhost:3000 \
    CORS_ALLOWED_ORIGINS=http://localhost:3000 \
    NEXT_PUBLIC_APP_ENV=local \
    NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1 \
    docker compose --env-file "$empty_env" -f "$REPO_ROOT/docker-compose.yml" config --quiet
  env \
    APP_ENV=local \
    SECURE_SSL_REDIRECT=false \
    POSTGRES_DB=ci_db \
    POSTGRES_USER=ci_user \
    POSTGRES_PASSWORD=ci-only-password \
    DJANGO_SECRET_KEY=ci-only-secret-key-with-more-than-fifty-characters-000000 \
    DJANGO_DEBUG=false \
    DATABASE_URL=postgresql://ci_user:ci-only-password@postgres:5432/ci_db \
    REDIS_URL=redis://redis:6379/0 \
    CELERY_BROKER_URL=redis://redis:6379/1 \
    SMS_PROVIDER=mock \
    SMS_VERIFICATION_HMAC_KEY=ci-only-sms-hmac-key-with-more-than-fifty-characters-000000 \
    QUOTA_IDEMPOTENCY_HMAC_KEY=ci-only-quota-hmac-key-with-more-than-fifty-characters-000000 \
    PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY=ci-only-plan-change-hmac-key-with-more-than-fifty-characters-000000 \
    WEB_IMPORT_IDEMPOTENCY_HMAC_KEY=ci-only-web-import-hmac-key-with-more-than-fifty-characters-000000 \
    ALLOWED_HOSTS=localhost,api \
    CSRF_TRUSTED_ORIGINS=http://localhost:3000 \
    CORS_ALLOWED_ORIGINS=http://localhost:3000 \
    NEXT_PUBLIC_APP_ENV=local \
    NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1 \
    docker compose --env-file "$empty_env" -f "$REPO_ROOT/docker-compose.yml" \
      build api celery celery-beat frontend
}

case "$MODE" in
  backend) check_backend ;;
  frontend) check_frontend ;;
  git) check_git_hygiene ;;
  actionlint) check_actionlint ;;
  gitleaks) check_gitleaks ;;
  security)
    check_git_hygiene
    check_actionlint
    check_gitleaks
    ;;
  docker) check_docker ;;
  all)
    check_backend
    check_frontend
    check_git_hygiene
    check_actionlint
    check_gitleaks
    check_docker
    ;;
esac
