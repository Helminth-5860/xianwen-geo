# XW-0113 Quota Accounts and Immutable Ledger

## Scope

XW-0113 adds the independent `apps.quotas` Django application. PostgreSQL is the
only source of truth for quota balances, holds, idempotency evidence, and ledger
history. Redis is not used for balance data or locking.

This implementation does not add Subject foreign keys or bare subject UUID
accounts. Subject-level quota definitions remain in the static catalog and in
the immutable subscription snapshot until the real Subject model exists.
`subject_active_limit` is not a ledger quota.

The implementation does not expose reset, renewal, upgrade, payment, order, or
business-task APIs. `create_cycle_batch` is an internal primitive reserved for
XW-0115; it creates a new account batch instead of mutating a previous cycle.

## Static catalog

`apps.quotas.catalog.QUOTA_CATALOG` owns the quota key, source limit key, unit,
scope, reset type, subject-level flag, and integer bounds. Snapshot validation
rejects booleans, negative values, unknown or missing definitions, and values
outside the signed PostgreSQL bigint range.

The five current non-subject accounts are created even when entitlement is zero:

- `detection_points`
- `article_credits`
- `image_credits`
- `storage_bytes`
- `assistant_messages`

## Data model

`QuotaAccount` binds a user, immutable Subscription, quota definition, batch,
immutable entitlement amount, optional cycle window, current available/frozen
balances, version, ledger sequence, and last ledger entry. It has no independent
status or expiry field; availability is derived from the active Subscription and
the account cycle window.

`QuotaHold` binds one business target to one account with
`UNIQUE(account, business_type, business_id)`. Its state machine is
`open -> partially_settled -> settled`. Requested amount is positive,
consumed/released amounts are monotonic, their total cannot exceed requested,
and settled is irreversible.

`QuotaLedgerEntry` is append-only. Sequence starts at 1 and is strictly
increasing per account through `UNIQUE(account, sequence)`. Replay and
verification use sequence rather than timestamp or UUID.

## Database guards

Migration `quotas.0002_postgresql_guards` installs PostgreSQL triggers that:

- block QuotaAccount and QuotaHold deletion;
- block QuotaLedgerEntry update and deletion;
- protect account bindings, entitlement, and cycle fields;
- reject direct balance changes without the matching next ledger entry;
- validate ledger before/delta/after formulas, sequence, account version,
  bindings, last entry, and final balance;
- protect hold bindings, monotonic settlement, and the settled terminal state.

Application model methods and protected QuerySets provide an earlier guard, but
the PostgreSQL triggers remain authoritative against raw SQL.

## Transactions and locks

All write services use PostgreSQL transactions and the lock order:

`Subscription -> QuotaAccount -> QuotaHold`

Future multi-account callers must sort account UUIDs. XW-0113 does not implement
cross-account consumption.

Freeze requires an effective active Subscription. An already-created hold can
still be consumed or released after the Subscription expires or terminates.
Release is always allowed for an open remainder so frozen quota cannot become
permanent.

Subscription creation calls `initialize_subscription_accounts` inside the same
outer transaction as Subscription, SubscriptionEvent, application activation,
PlanApplicationEvent, Notification, and AuditEvent. Any failure rolls back the
whole operation.

## Idempotency and privacy

Clients send a printable 16-128 character `Idempotency-Key` for administrator
adjustments. Internal quota services derive versioned HMAC digests from the
operation, user, account, business target, and canonical request digest.

Production requires a separate strong `QUOTA_IDEMPOTENCY_HMAC_KEY`. It may not
reuse Django, SMS, database, or Redis secrets. The raw key is never persisted or
placed in logs, errors, AuditEvent, Notification, or ApprovalRequest payloads.
Risk handlers receive derived digests only.

## Public APIs

User Session APIs:

- `GET /api/v1/quotas`
- `GET /api/v1/quota-ledger`

Administrator Session APIs:

- `GET /api/v1/admin/quota-accounts`
- `GET /api/v1/admin/quota-ledger`
- `POST /api/v1/admin/quota-accounts/{account_id}/adjust/grant`
- `POST /api/v1/admin/quota-accounts/{account_id}/adjust/compensate`
- `POST /api/v1/admin/quota-accounts/{account_id}/adjust/manual-deduct`

The three administrator adjustments require `quotas.adjust`, CSRF,
`expected_version`, a positive integer amount, a normalized reason, and an
Idempotency-Key. Their RiskAction minimum and current modes are fixed to
`two_person`.

Administrator reads apply CustomerAssignment `own/role/all` scope before
filters; out-of-scope objects return 404. User serializers omit business IDs,
idempotency/request digests, internal notes, approval payloads, snapshots, and
actor details. No public quota reset route exists.

## Migrations and rollback

Migration order:

1. `quotas.0001_initial` creates the three models, constraints, and indexes.
2. `quotas.0002_postgresql_guards` installs database triggers.
3. `quotas.0003_backfill_subscription_accounts` uses historical models to
   validate immutable snapshots and idempotently initialize existing
   Subscriptions.
4. `admin_rbac.0012_seed_quota_catalog` seeds permissions, menu capability,
   RiskAction, and fixed two-person policies.

The backfill reverse is intentionally a no-op so quota evidence is not silently
deleted. Reversing the initial schema deletes ledger evidence and is destructive.
Production rollback must be reviewed and backed up first; prefer a forward fix
or database restore. This work does not connect to Tencent Cloud services.

## Verification

Fast local checks:

```powershell
.\scripts\check.ps1 all
```

Real isolated PostgreSQL/Redis guard and concurrency checks:

```powershell
.\scripts\test-quotas.ps1
```

The dedicated suite verifies concurrent contiguous sequences, unique business
holds across different idempotency keys, raw SQL guards, irreversible settlement,
post-termination settlement, migration idempotency, transaction rollback, and
two-person exactly-once execution. The GitHub Actions Docker Compose job runs the
same core command and cleans isolated containers, networks, and volumes.
