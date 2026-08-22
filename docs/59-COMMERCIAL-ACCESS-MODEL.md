# Commercial access model

The commercial access boundary has three product identities:

- `PLATFORM_SUPER_ADMIN`: global platform governance, tenant management, global security and
  provider/runtime configuration.
- `TENANT_ADMIN`: complete tenant operational navigation and data limited to `User.tenant_id`.
- `END_USER`: the real `/workspace` and all product routes, even without an active plan.

## Visibility and execution

Tenant identity determines which data can be read. Plans and quota determine whether a metered
operation can execute; they never hide the workspace, a normal overview, or a product route.
Security-critical mutations remain outside the tenant baseline permissions and keep the existing
RBAC, confirmation, dual-approval, current-password and SMS Step-Up controls.

## Tenant foundation and backfill

`users.Tenant` owns display name, brand name and an opaque logo reference. `User.tenant` is the
single ownership root for subjects, detection jobs, reports, articles, images, quota and operations
records. Migration `users.0011` creates a deterministic legacy default tenant and assigns every
existing non-superuser account to it. Platform super administrators remain tenantless. The migration
is additive and reversible and does not rewrite business records.

Existing subject-level report branding remains available as a more specific override; it is not a
substitute for tenant isolation.
