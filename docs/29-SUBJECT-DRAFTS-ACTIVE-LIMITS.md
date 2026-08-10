# XW-0202 Subject drafts and active limits

## Scope

XW-0202 adds user-owned subject drafts to the existing `apps.subjects` catalog.
It creates `Subject`, `SubjectVersion`, `SubjectEvent`, and `SubjectContext`,
but deliberately provides no production write path for `SubjectVersion`.
The first formal version remains version 1 and is owned by XW-0203.

This task does not add formal commit/version APIs, AI enrichment, file uploads,
COS, keywords, subject quota accounts, or later business modules. PostgreSQL is
the only source of truth for subject state, current selection, version checks,
and active-limit concurrency. Redis does not store balances or subject locks.

## Frozen schema semantics

Creation requires `expected_schema_version`. The service locks the
`SubjectType`, rebuilds a canonical schema snapshot with the independent
snapshot builder, serializes compact sorted-key JSON, and stores its SHA-256
digest and `schema_snapshot_format_version=1`.

The following subject bindings are immutable:

- user and subject type;
- schema version, canonical schema snapshot, digest, and format version;
- creation identity and timestamps protected by the model and database guards.

Defaults from the snapshot are materialized into `draft_values`, then user
`initial_values` are overlaid and validated. Existing drafts are always
validated against their own stored snapshot. A later catalog label, option,
required flag, or status change cannot alter historical draft semantics.

The user detail response contains only a safe `form_schema` projection from the
stored snapshot. It never exposes the raw snapshot, digest, internal Config or
Definition identifiers. The web editor consumes this projection and never calls
the current `/subject-types/{id}/form-schema` endpoint for an existing subject.

## Status and draft rules

The only states and transitions are:

- `draft -> active`;
- `draft -> archived`;
- `active -> archived`;
- `archived -> active`.

Draft does not consume an active slot. Active consumes one slot but does not
mean required fields are complete or a formal version exists. Archived is
read-only history. PostgreSQL rejects physical Subject deletion, illegal raw
status recovery, immutable binding mutation, and archived `draft_values`
updates.

PATCH semantics are partial: omitted fields remain unchanged, null clears a
nullable value, an empty array clears a multi-select, and an unknown field
returns `SUBJECT_FIELD_VALUES_INVALID`. Required-field completeness remains
for XW-0203. Image and file fields accept only null; no upload endpoint exists.

## Account and subscription rules

An account with `account_status=active` may edit its own draft or active
subjects even after a subscription expires. Archived subjects are read-only.
`cancel_pending` is read-only; frozen or cancelled accounts cannot write.
Approval status alone does not block subject drafts.

Without a currently effective subscription, a user may have at most one current
draft and cannot activate it. Archived subjects do not consume this free draft
slot. With an effective subscription, XW-0202 adds no draft-count cap.

Activation requires an effective active subscription in the half-open interval
`starts_at <= now < ends_at`, an active current SubjectType, and a valid
non-boolean integer `subject_active_limit` within the static maximum.
Missing, boolean, negative, unknown-type, or oversized entitlement values fail
closed as `SUBJECT_ENTITLEMENT_INTEGRITY_ERROR`; they are never treated as
zero or unlimited.

The reusable guard is called when formal subscriptions, trials, immediate plan
changes, trial conversions, and scheduled renewals grant target entitlements.
A target below the current active count returns
`SUBJECT_LIMIT_RECONCILIATION_REQUIRED` and never auto-archives subjects.
Plan-change preview reports active count, target limit, and required archives;
submit and execution recalculate. Final execution validates under the User row
lock.

For an approved scheduled renewal, activation uses the lower of the current and
future target limits. If the renewal remains over limit at execution, the
source subscription still expires under XW-0115 rules, while the change remains
scheduled with a recoverable reconciliation error and retry time.

## Locking and current subject

Every status change locks User first. Subject paths use:

`User -> effective Subscription (when needed) -> Subject -> SubjectContext`.

Existing plan-change and renewal paths retain their earlier Plan and PlanVersion
locks before User. No Subject-to-User reverse lock order is introduced.

`SubjectContext` is one immutable row per user. Its user binding and row cannot
be deleted. Current may be null but otherwise must reference a non-archived
subject owned by the same user. A deferred PostgreSQL constraint permits archive
and current clearing in one transaction.

The first subject becomes current. Draft or active subjects may be selected.
Archiving current clears it atomically. Activation does not switch current.
Setting the existing current subject with the correct context version is a
no-op and does not write a duplicate event.

## API and errors

Authenticated user APIs are:

- `GET /api/v1/subjects`;
- `POST /api/v1/subjects`;
- `GET /api/v1/subjects/{id}`;
- `PATCH /api/v1/subjects/{id}/draft`;
- `POST /api/v1/subjects/{id}/archive`;
- `POST /api/v1/subjects/{id}/activate`;
- `PUT /api/v1/subjects/current`.

All object queries first scope by `user=request.user`; cross-user access is
404. Writes use real CSRF, strict serializers, expected object/context versions,
the standard envelope, request ID, and simplified-Chinese user messages.
Stable task errors include schema mismatch, invalid field values, subject and
context version conflicts, state conflict, plan required, limit reached,
reconciliation required, and entitlement integrity failure.

There is no commit, versions, delete, restore, upload, enrichment, administrator
Subject API, CustomerAssignment scope, or RiskAction in XW-0202.

## Database migrations and rollback

- `subjects.0004_*` creates Subject, SubjectVersion, SubjectEvent, and
  SubjectContext with their indexes and constraints.
- `subjects.0005_subject_data_postgresql_guards` installs PostgreSQL guards for
  immutable bindings, legal state transitions, append-only events/versions,
  delete rejection, context ownership, and deferred consistency.

No historical Subject or SubjectVersion is fabricated. Reversing 0005 only
removes database guard functions and triggers; it does not remove evidence.
Reversing 0004 drops all XW-0202 subject-domain tables and therefore destroys
draft, context, event, and reserved version evidence. Production rollback must
stop writes, audit references, and take a backup. Forward repair or backup
restore is preferred.

## Verification

Fast checks run with `./scripts/check.sh all` or
`.\\scripts\\check.ps1 all`. The real PostgreSQL/Redis suite runs with
`./scripts/test-subject-schema.sh` or
`.\\scripts\\test-subject-schema.ps1`; the Compose service executes both
the XW-0201 schema suite and `tests/test_subject_drafts_postgres.py`.

The dedicated suite verifies raw-SQL immutability and delete guards, deferred
context consistency, no-plan and last-active-slot concurrency, event rollback,
frozen snapshot editing, absence of SubjectVersion writes, and Redis
independence. Unit/API tests cover stable envelopes, CSRF, user scoping,
default materialization, account status boundaries, limit guards, and read-only
GET behavior. Frontend Testing Library tests prove that existing editing uses
the persisted detail schema and does not fetch the current catalog schema.
