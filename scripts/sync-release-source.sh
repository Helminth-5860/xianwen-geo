#!/usr/bin/env bash
set -euo pipefail

: "${EXPECTED_SHA:?EXPECTED_SHA must be a full 40-character Git SHA}"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo 'EXPECTED_SHA must be a full lowercase Git SHA.' >&2; exit 2; }
repo="${REPOSITORY:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
[[ -z "$(git -C "$repo" status --porcelain)" ]] || { echo 'Release source sync requires a clean worktree.' >&2; exit 3; }
[[ "$(git -C "$repo" branch --show-current)" == 'develop' ]] || { echo 'Release source sync requires the develop branch.' >&2; exit 3; }
git -C "$repo" pull --ff-only origin develop
head_sha="$(git -C "$repo" rev-parse HEAD)"
remote_sha="$(git -C "$repo" rev-parse origin/develop)"
[[ "$head_sha" == "$EXPECTED_SHA" && "$remote_sha" == "$EXPECTED_SHA" ]] || { echo 'Synced source does not equal the exact expected SHA.' >&2; exit 4; }
printf '{"status":"SYNCED","expected_sha":"%s","head_sha":"%s","ff_only":true}\n' "$EXPECTED_SHA" "$head_sha"
