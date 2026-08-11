# XW-0203 Subject versions, names, and products

## Scope

XW-0203 turns a saved Subject draft into immutable formal evidence. The first
successful commit is version 1; later versions are strictly contiguous. No
XW-0202 history is fabricated. Draft and active subjects may commit, while an
archived subject remains read-only. Commit does not activate a subject, consume
an active slot, require a Subscription, or create quota facts.

AI enrichment, keywords, GEO detection, file/COS support, Subject quotas,
administrator Subject editing, delete/restore, and automatic retest clearing are
outside this task.

## Source of truth and transaction

`POST /api/v1/subjects/{id}/commit` accepts only `expected_version` and the exact
set of product candidate confirmations. Under one PostgreSQL transaction it
locks User then Subject, reads the latest persisted `draft_values` and the
Subject's immutable schema snapshot, validates required fields, derives semantic
facts, creates SubjectVersion/SubjectName/SubjectProduct, advances
`current_version`, updates `retest_required`, and appends a bound SubjectEvent.
Any failure rolls the complete fact set back.

The request cannot supply field values, a schema snapshot or digest, a version
number, an official name, or arbitrary products. The first formal version sets
`retest_required=false`; every later committed version sets it to true. XW-0203
does not clear the flag.

## Frozen schema and semantic derivation

Required-field validation and all names/products are derived from the Subject's
frozen schema. Historical version reads use that version's own copied snapshot,
never the mutable SubjectType catalog. Values are normalized with Unicode NFKC,
collapsed whitespace, control-character rejection, and casefold matching.
Choice fields resolve their saved option label from the frozen snapshot.

Allowed name-role/type pairs are:

- official_name: text, single, or select;
- alias, english_name, product: text, single, select, or multi;
- every other field type: name_role none only.

Serializer and service validation reject new invalid pairings. PostgreSQL
`subjects_config_name_role_type` provides a deferred raw-SQL guard without
rewriting historical catalog rows.

Every SubjectVersion contains one and only one official SubjectName. Names and
products are append-only. Product `candidate_key` values are deterministic and
server-generated. The commit request must confirm every current candidate once;
`include_in_mention=true` requires `uniqueness_confirmed=true`.

`field_values_digest` covers canonical draft values. `semantic_digest` binds the
frozen schema digest, field values, and product confirmation semantics. An
identical semantic digest returns `SUBJECT_VERSION_NO_CHANGES`; changing only a
valid product confirmation can therefore create a new formal version.

## Database enforcement and migration

Migration `subjects.0006_subject_versions_names_products` adds the formal
fields/tables and rejects an upgrade containing any pre-existing SubjectVersion
row so operators must review unexpected evidence rather than guess pointers or
semantics. It creates no formal data, name, product, or event. Once formal
versions exist, destructive reverse is blocked and requires a reviewed backup or
forward fix.

Migration `subjects.0007_subject_version_postgresql_guards` installs:

- `subjects_guard_subject_version` for immutable versions, schema binding, and
  contiguous insert sequence;
- `subjects_guard_semantic` for immutable/non-deletable names and products and
  refusal to append semantics after a version is finalized;
- `subjects_assert_version_chain` and deferred chain triggers for first version
  1, no gaps, a same-Subject maximum `current_version`, exactly one official
  name, and correctly bound `version_committed` events;
- the name-role/type deferred catalog guard.

Raw SQL cannot update/delete formal versions, names, products, or events, move
`current_version` backward, finalize a gap, or bind a version to a different
schema snapshot.

## API and privacy

- `POST /api/v1/subjects/{id}/commit`;
- `GET /api/v1/subjects/{id}/versions`;
- `GET /api/v1/subjects/{id}/versions/{version_id}`.

All endpoints require an authenticated, available account and use the existing
Session/CSRF envelope. The write requires a real CSRF token. Stable business
errors cover missing required fields, invalid semantics/product confirmation,
no changes, stale version, archived state, and unavailable account.

User responses expose safe display values and frozen public form schema only.
They do not expose raw schema snapshots, schema/field/semantic digests, normalized
matching values, internal actor data, or audit payloads.

## Verification

Fast tests cover strict request fields, required/state/account boundaries,
normalization, frozen labels, product spoofing, semantic no-change behavior, and
failure rollback. The real PostgreSQL suite additionally covers concurrent
first commit, strict version chains/current max, schema and event binding,
raw-SQL immutability, name-role guards, fault injection, and migration preflight.
Run it through `./scripts/test-subject-schema.sh` or
`.\\scripts\\test-subject-schema.ps1`; the Compose service also uses real Redis
to preserve the project integration boundary.
