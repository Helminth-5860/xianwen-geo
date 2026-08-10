# XW-0115 Cycle reset and expiry processing

## Scope

PostgreSQL remains the sole source of truth for subscription lifecycle, quota
batches, ledger entries, retries, and exactly-once evidence. Redis is only the
Celery broker/cache and a Redis outage cannot create lifecycle facts.

There is no public execute, reset, cycle-advance, history-edit, or automatic
hold-release API. User and administrator GET endpoints remain read-only.

## Scheduled renewal

A scheduled renewal has already completed two-person approval. System execution
validates its immutable ApprovalRequest binding, canonical digest, target
PlanVersion, and recorded unavailable confirmation. It does not depend on the
requester's current role, permission, or customer assignment.

The target window is deterministic:

- starts_at equals effective_at.
- ends_at equals effective_at plus target valid_days.
- a delayed worker never restarts the duration from its actual execution time.
- an entirely elapsed target window fails with RENEWAL_WINDOW_ELAPSED.
- archived targets fail; offline or retired targets require the confirmation
  captured by the original approval; no version is substituted.

SubscriptionChange adds the terminal failed state. scheduled may transition only
to executed, cancelled, or failed; terminal states cannot be restored. Permanent
domain errors fail the change. Holds and frozen quota persist a safe error code,
retry_count, and next_attempt_at while the change remains scheduled.

Expiry and renewal deliberately race safely. The source converges to expired at
ends_at even when renewal is blocked. A later renewal can execute from that
expired source. A terminated source can never renew. The expired event is
idempotent and is not duplicated.

## Final expiry disposition

expiry_quota_policy is read from the immutable entitlement snapshot. A missing
value defaults to zero and an unknown value is an integrity failure.

- zero writes expiry_forfeit and leaves no available balance.
- freeze keeps the historical balance but it is not consumable.
- retain may migrate only through an approved scheduled renewal. Without a
  successful renewal the balance remains historical and unavailable.

When a renewal is still scheduled, expiry does not destroy balance that may need
to migrate. Cancellation or permanent failure then applies final disposition.
A release after a zero disposition writes expiry_late_release_forfeit in the
same settlement transaction.

## Monthly cycle batches

Only catalog entries with reset_type=monthly are advanced. In the current
catalog this is assistant_messages. Each boundary:

1. writes cycle_forfeit for available balance in the previous primary batch;
2. leaves frozen quota attached to its existing Hold;
3. creates a new primary QuotaAccount batch;
4. writes its sequence-1 initialize ledger entry; and
5. records one immutable QuotaCycleReset.

Carryover batches never reset. A late release into an ended monthly batch writes
cycle_late_release_forfeit immediately. A boundary equal to Subscription.ends_at
does not create another batch.
When a delayed scheduled renewal creates its successor, the renewal transaction
advances every elapsed monthly boundary in order before it can complete. The
successor therefore already has a batch covering the actual execution instant;
any catch-up failure rolls back the renewal and all of its lifecycle facts.


cycle_anchor_time is immutable and historical subscriptions are backfilled from
starts_at in Asia/Shanghai. The original day and time are recalculated for each
month independently, with month-end clamping, so a 31st anchor does not drift
after February.

QuotaCycleReset is unique by subscription, quota type, and boundary. Deferred
PostgreSQL triggers validate continuous windows, matching user/subscription/type,
the next initialize entry, the previous forfeit entry, and the subscription end
boundary. QuotaCycleReset and QuotaExpiryDisposition are append-only.

## Celery behavior

Static Beat entries scan due renewals, subscription expiries, and quota cycle
accounts. Scanners page IDs and enqueue item tasks; they do not hold a large
transaction. All entry points call the same idempotent domain services.

Workers use acks_late, task_reject_on_worker_lost, prefetch=1, and finite time
limits. Only PostgreSQL operational/connection failures use bounded exponential
Celery retry. Duplicate, not-due, already-done, blocked, and permanent domain
results end normally after their durable state is recorded. Celery task IDs and
the Beat schedule file are not exactly-once evidence. The schedule file lives at
/tmp/xianwen-celerybeat-schedule in Compose and is not committed.

## Migration and rollback

Plans 0012 backfills cycle_anchor_time and scheduled next_attempt_at using
historical models; it does not fabricate past reset or expiry facts. Plans 0013
and quotas 0009 install PostgreSQL guards. Quotas 0008 creates lifecycle evidence
tables and ledger action values. Users 0007 expands the notification catalog.

Reverse trigger migrations only remove the new protection; they cannot safely
undo executed renewals, quota forfeits, reset facts, or expiry facts. Before any
production reverse migration, stop lifecycle workers, audit references, and take
a verified backup. Prefer a forward repair or backup restoration.

## Verification

Fast checks:

    .\scripts\check.ps1 all
