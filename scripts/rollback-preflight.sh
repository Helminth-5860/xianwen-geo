#!/usr/bin/env bash
set -euo pipefail

: "${CURRENT_SHA:?CURRENT_SHA must be a full 40-character Git SHA}"
: "${TARGET_SHA:?TARGET_SHA must be a full 40-character Git SHA}"
: "${BACKUP_ARTIFACT:?BACKUP_ARTIFACT is required}"
: "${BACKUP_CHECKSUM:?BACKUP_CHECKSUM is required}"
[[ "$CURRENT_SHA" =~ ^[0-9a-f]{40}$ && "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo 'Current and target SHA values must be full lowercase Git SHAs.' >&2; exit 2; }
repo="${REPOSITORY:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
pg_restore_bin="${PG_RESTORE_BIN:-pg_restore}"
[[ -z "$(git -C "$repo" status --porcelain)" ]] || { echo 'Rollback preflight requires a clean worktree.' >&2; exit 3; }
[[ "$(git -C "$repo" rev-parse HEAD)" == "$CURRENT_SHA" ]] || { echo 'Current deployed source does not equal CURRENT_SHA.' >&2; exit 4; }
git -C "$repo" cat-file -e "${TARGET_SHA}^{commit}"
git -C "$repo" merge-base --is-ancestor "$TARGET_SHA" "$CURRENT_SHA" || { echo 'Rollback target must be an ancestor of CURRENT_SHA.' >&2; exit 4; }
[[ "$(sha256sum "$BACKUP_ARTIFACT" | awk '{print $1}')" == "$BACKUP_CHECKSUM" ]] || { echo 'Rollback backup checksum mismatch.' >&2; exit 5; }
"$pg_restore_bin" --list "$BACKUP_ARTIFACT" >/dev/null
migration_diff="$(git -C "$repo" diff --name-only "$TARGET_SHA" "$CURRENT_SHA" -- ':(glob)backend/**/migrations/*.py')"
[[ -z "$migration_diff" ]] || { echo 'ROLLBACK_MIGRATION_REVIEW_REQUIRED: migration files differ between target and current SHA.' >&2; exit 6; }
printf '{"status":"READY","current_sha":"%s","target_sha":"%s","backup_verified":true,"migration_diff_count":0,"rollback_performed":false}\n' "$CURRENT_SHA" "$TARGET_SHA"
