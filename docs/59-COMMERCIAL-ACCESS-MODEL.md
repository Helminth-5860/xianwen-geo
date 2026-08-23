# Commercial access model

The only supported commercial hierarchy is:

```text
SUPER_ADMIN
    -> ADMIN
        -> USER
```

- `SUPER_ADMIN` governs every ADMIN and can operate on every USER, but never owns a USER.
- `ADMIN` is an agent account and can operate only on USER records directly assigned to it.
- `USER` is one enterprise customer account. It uses `/workspace` and has no personnel,
  organization, role, or permission administration capability.

`/admin` is reserved for `SUPER_ADMIN` and `ADMIN`; `/workspace` is reserved for `USER`.
ADMIN creation, profile changes, role changes, and status changes are server-enforced
SUPER_ADMIN operations. Public registration always creates a USER and cannot accept role or
staff fields.

## Authoritative ownership boundary

`admin_rbac.CustomerAssignment` is the sole authorization boundary between an ADMIN and a USER:

- `customer` is one-to-one, so a USER can have at most one owner;
- `owner_admin` is non-null, so an ownership row cannot be unassigned;
- the owner must be a non-super ADMIN with a role;
- ADMIN queries always filter by `owner_admin`, regardless of the legacy role `data_scope` value;
- SUPER_ADMIN queries may cross ADMIN boundaries.

`User.tenant` remains only for compatibility and branding. Tenant equality, role equality, and
role `data_scope=ALL` must never broaden USER or business-data access. Subjects, detection jobs,
reports, articles, images, subscriptions, quota, and operations continue to inherit their boundary
from their protected USER foreign key. Plans and quota determine execution eligibility, not whether
workspace navigation is visible.

## Registration and migration

Every ADMIN has a random, unique `registration_channel_key`. SUPER_ADMIN can obtain a time-limited
signed link in the form `/register?ref=<opaque-signed-token>` from the ADMIN detail page. The token
contains the opaque channel key, not an ADMIN primary key, and its signature and age are verified by
the backend. `REGISTRATION_REF_MAX_AGE_SECONDS` controls validity (30 days by default).

The registration page validates `ref` before enabling its form. The registration transaction locks
and revalidates the referenced ADMIN, then creates the USER and its `CustomerAssignment` together.
Missing, invalid, expired, tampered, disabled/locked ADMIN, inactive role, or direct `admin_id`
attempts fail closed. ADMIN status changes therefore invalidate outstanding links immediately.

Migration `admin_rbac.0022` backfills every existing non-staff/non-super USER. It preserves an
existing valid assignment; otherwise it requires exactly one eligible non-super ADMIN in the same
legacy tenant. Ambiguous or missing ownership aborts migration instead of guessing. It then makes
`owner_admin` non-null. Operators must resolve ambiguous legacy tenants before retrying migration.
The same-tenant inference exists only in this one-time legacy migration and is never used by live
registration.

This change does not alter Provider, Execution, Scoring, subscription, or quota-ledger semantics.
