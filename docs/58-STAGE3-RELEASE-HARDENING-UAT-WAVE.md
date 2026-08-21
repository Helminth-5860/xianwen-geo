# Stage 3 Release Hardening / Commercial Operations / UAT Wave

## Frozen boundary

This wave implements the repository-side `CODE_ONLY` portion of `XW-0901`—`XW-1009`.
It does not change GEO scoring, immutable report evidence, quota semantics, or Stage 2 content
contracts. It must not be used to claim that external release gates have passed.

`CODE_ONLY` includes:

- customer status, tags, owner-aware profiles, append-only contact logs, and follow-ups;
- safe usage/task projections, article/image moderation queues, announcements, feedback, and
  one-session read-only support views;
- a permission-protected operational dashboard and machine-readable release readiness;
- security headers, bounded request/data handling, ClamAV adapter support, production configuration
  validation, worker heartbeat metadata, and no-secret operational output;
- backup artifact checksum/catalog verification, ff-only source sync, exact SHA release preflight,
  migration-aware rollback preflight, atomic `DEPLOYED_SHA` publication, security regression tests,
  and automated code-level UAT.

`EXTERNAL_GATE` remains mandatory for:

- real Tencent COS private bucket, region, endpoint, lifecycle, CORS, credentials, and smoke;
- real Tencent SMS credentials, approved templates/signature, delivery test, and administrator MFA;
- real DeepSeek, eight detection-provider, and Ark image credentials and HTTPS smoke;
- Staging/Production PostgreSQL migrations, Redis writes, worker rollout and heartbeats;
- DNS, TLS, security groups, traffic cutover, production backup creation, isolated restore exercise,
  performance test, and final human UAT.

The release-readiness response is fail-closed. Missing external evidence returns `NOT_READY`; it
never synthesizes success and never exposes secrets or raw configuration.
Each real external smoke must later append a short-lived `release_evidence` row for the exact deploy
SHA by using `record_release_evidence`. The table is append-only in ORM and PostgreSQL; a configured
credential without matching, unexpired smoke evidence can never make the release ready.

## Commercial operations invariants

- Every admin endpoint requires a secure admin session plus an explicit RBAC permission and reuses
  the existing own/role/all customer scope.
- Customer contact logs and support-view access logs are append-only in ORM and PostgreSQL.
- Profile, follow-up, feedback, announcement, moderation, and support-view changes use optimistic
  versions and append a safe `AuditEvent` without contact text, feedback text, prompt, or secrets.
- Support views return a small read-only summary. They cannot modify data, export, submit AI work,
  consume quota, expose phone numbers, or reveal prompt/provider configuration.
- Moderation creates new evidence and never edits prior reviews. A system-responsibility decision
  creates a safe compensation-required alert; quota changes continue through the existing approved
  quota-adjustment workflow.

## Safe summary contract

Provider smoke and release tooling may output only bounded status metadata such as:

- stable status/error code;
- model and capability identifiers;
- latency and token/usage counts;
- degraded flag and `provider_request_id`;
- object counts, migration count, expected/observed worker queue names, and checksum presence.

It must not output API keys, Authorization values, encryption/HMAC values, `prompt`, answer body,
raw provider JSON, `reasoning_content`, database/Redis passwords, or storage credentials. 中文约束：
不得输出 prompt、回答正文或任何 secret。

## Canonical release preflight

`sync-release-source` requires clean `develop` and uses only `pull --ff-only`. The release preflight
requires a clean worktree, a full exact SHA, and `HEAD == origin/develop == exact SHA`; it verifies
migration state and invokes the fail-closed readiness command. `rollback-preflight` rejects a target
that is not an ancestor, verifies the backup checksum/catalog, and stops for any migration diff.
`publish-deployed-sha` writes through a same-directory temporary file only after readiness passes.
The backup verifier reads an existing artifact, checks SHA-256 and `pg_restore --list`, and never
creates, uploads, or claims to have restored a backup. Catalog verification leaves
`restore_verified_at` empty; only the later isolated restore gate may supply that evidence.

Isolated PostgreSQL/Redis acceptance is run with `scripts/test-stage3-release.ps1` or
`scripts/test-stage3-release.sh`. These suites may write only to disposable Docker volumes and test
Redis databases; they are not production rollout commands.

本波不得执行真实部署，不得调用真实 Provider，不得写入生产数据。Rollout、rollback、fresh
backup、migration apply、health/worker gates and invocation of the checked-in rollback/marker tools
remain deployment-line actions after all `EXTERNAL_GATE` evidence is available.
