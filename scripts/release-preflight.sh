#!/usr/bin/env bash
set -euo pipefail

: "${EXPECTED_SHA:?EXPECTED_SHA must be a full 40-character Git SHA}"
if [[ ! "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'EXPECTED_SHA must be a full lowercase Git SHA.' >&2
  exit 2
fi

repo="${REPOSITORY:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
python_bin="${PYTHON_BIN:-python}"
git_root="$(git -C "$repo" rev-parse --show-toplevel)"
if [[ "$(cd "$git_root" && pwd)" != "$(cd "$repo" && pwd)" ]]; then
  echo 'Repository must be the exact Git worktree root.' >&2
  exit 2
fi
if [[ -n "$(git -C "$repo" status --porcelain)" ]]; then
  echo 'Release preflight requires a clean worktree.' >&2
  exit 3
fi
if [[ "$(git -C "$repo" branch --show-current)" != "develop" ]]; then
  echo 'Release preflight requires the develop branch.' >&2
  exit 3
fi

git -C "$repo" fetch origin develop
head_sha="$(git -C "$repo" rev-parse HEAD)"
develop_sha="$(git -C "$repo" rev-parse origin/develop)"
if [[ "$head_sha" != "$EXPECTED_SHA" || "$develop_sha" != "$EXPECTED_SHA" ]]; then
  echo 'HEAD and origin/develop must both equal the exact expected SHA.' >&2
  exit 4
fi

(
  cd "$repo/backend"
  "$python_bin" manage.py migrate --plan --check
  "$python_bin" manage.py release_readiness
)
printf '{"status":"READY","expected_sha":"%s","head_sha":"%s","origin_develop_sha":"%s","dirty":false,"branch":"develop","deployment_performed":false}\n' \
  "$EXPECTED_SHA" "$head_sha" "$develop_sha"
