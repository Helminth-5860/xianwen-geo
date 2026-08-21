#!/usr/bin/env bash
set -euo pipefail

: "${EXPECTED_SHA:?EXPECTED_SHA must be a full 40-character Git SHA}"
: "${MARKER_PATH:?MARKER_PATH is required}"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo 'EXPECTED_SHA must be a full lowercase Git SHA.' >&2; exit 2; }
repo="${REPOSITORY:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
python_bin="${PYTHON_BIN:-python}"
[[ -z "$(git -C "$repo" status --porcelain)" ]] || { echo 'Marker publication requires a clean worktree.' >&2; exit 3; }
[[ "$(git -C "$repo" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || { echo 'HEAD does not equal EXPECTED_SHA.' >&2; exit 4; }
(cd "$repo/backend" && "$python_bin" manage.py release_readiness) || { echo 'Release readiness is NOT_READY; marker was not written.' >&2; exit 5; }
marker_parent="$(dirname "$MARKER_PATH")"
[[ -d "$marker_parent" ]] || { echo 'Marker parent directory must already exist.' >&2; exit 6; }
temporary="$(mktemp "${MARKER_PATH}.tmp.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
printf '%s\n' "$EXPECTED_SHA" >"$temporary"
chmod 0644 "$temporary"
mv -f "$temporary" "$MARKER_PATH"
trap - EXIT
printf '{"status":"PUBLISHED","deployed_sha":"%s","atomic_write":true,"rollout_performed":false}\n' "$EXPECTED_SHA"
