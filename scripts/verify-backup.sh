#!/usr/bin/env bash
set -euo pipefail

: "${EXPECTED_SHA:?EXPECTED_SHA must be a full 40-character Git SHA}"
: "${ARTIFACT:?ARTIFACT is required}"
: "${EXPECTED_CHECKSUM:?EXPECTED_CHECKSUM is required}"
repo="${REPOSITORY:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
pg_restore_bin="${PG_RESTORE_BIN:-pg_restore}"

if [[ -n "$(git -C "$repo" status --porcelain)" ]]; then
  echo 'Backup verification requires a clean worktree.' >&2
  exit 3
fi
if [[ "$(git -C "$repo" rev-parse HEAD)" != "$EXPECTED_SHA" ]]; then
  echo 'Backup verification SHA does not match HEAD.' >&2
  exit 4
fi
actual_checksum="$(sha256sum "$ARTIFACT" | awk '{print $1}')"
if [[ "$actual_checksum" != "$EXPECTED_CHECKSUM" ]]; then
  echo 'Backup checksum mismatch.' >&2
  exit 5
fi
"$pg_restore_bin" --list "$ARTIFACT" >/dev/null
printf '{"status":"VERIFIED","expected_sha":"%s","checksum_match":true,"pg_restore_catalog":"valid","backup_created":false}\n' "$EXPECTED_SHA"
