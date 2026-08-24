# Commercial access model

The only supported commercial hierarchy is:

```text
SUPER_ADMIN
    -> ADMIN -> assigned USER
    -> independent USER
```

- `SUPER_ADMIN` governs every ADMIN and can operate on every USER, but never owns a USER.
- `ADMIN` is an agent account and can operate only on USER records directly assigned to it.
- `USER` may be independent or associated with one ADMIN. It uses `/workspace` and has no personnel,
  organization, role, or permission administration capability.

`/admin` is reserved for `SUPER_ADMIN` and `ADMIN`; `/workspace` is reserved for `USER`.
ADMIN creation, profile changes, role changes, and status changes are server-enforced
SUPER_ADMIN operations. Public registration always creates a USER and cannot accept role or
staff fields.

## Authoritative ownership boundary

`admin_rbac.CustomerAssignment` is the sole authorization boundary between an ADMIN and a USER:

- `customer` is one-to-one, so a USER can have at most one associated ADMIN;
- `owner_admin` is nullable; null means the USER is independent;
- a non-null owner must be a non-super ADMIN with a role;
- ADMIN queries always filter by `owner_admin`, regardless of the legacy role `data_scope` value;
- SUPER_ADMIN queries may cross ADMIN boundaries.

`User.tenant` remains only for compatibility and branding. Tenant equality, role equality, and
role `data_scope=ALL` must never broaden USER or business-data access. Subjects, detection jobs,
reports, articles, images, subscriptions, quota, and operations continue to inherit their boundary
from their protected USER foreign key. Plans and quota determine execution eligibility, not whether
workspace navigation is visible.

## Registration and migration

`/register` is a public USER registration entry. Phone, SMS verification, nickname, and password
are sufficient. Registration creates an active USER, a nullable `CustomerAssignment`, establishes
a browser session, and sends the USER to `/workspace`.

Every ADMIN also has a random, unique `registration_channel_key`. SUPER_ADMIN can obtain a time-limited
signed link in the form `/register?ref=<opaque-signed-token>` from the ADMIN detail page. The token
contains the opaque channel key, not an ADMIN primary key, and its signature and age are verified by
the backend. `REGISTRATION_REF_MAX_AGE_SECONDS` controls validity (30 days by default).

When `ref` is valid, the transaction locks and revalidates the referenced ADMIN and associates the
new USER with it. Missing, invalid, expired, tampered, disabled/locked ADMIN, or inactive-role refs
do not block public registration; the USER is created independently and the page explains that the
invitation relationship is unavailable. A direct `admin_id`, role, staff, or superuser override is
always rejected.

Historical migration `admin_rbac.0022` backfilled every existing non-staff/non-super USER. It preserved an
existing valid assignment; otherwise it requires exactly one eligible non-super ADMIN in the same
legacy tenant. Ambiguous or missing ownership aborts migration instead of guessing. It then makes
`owner_admin` non-null. Forward migration `admin_rbac.0027` makes the field nullable and creates an
independent assignment row for any ordinary USER still missing one. The same-tenant inference exists
only in the historical migration and is never used by live registration.

This change does not alter Provider, Execution, Scoring, subscription, or quota-ledger semantics.
