# Subject risk catalog revisions and review (XW-0204)

## Scope

XW-0204 adds deterministic, local subject-risk classification and scoped manual review. It does not add AI classification, third-party moderation, production risk keywords, industry rules, keyword generation, GEO detection, or XW-0205 behavior.

`SubjectRiskType` and `SubjectRiskRule` are mutable draft configuration only. The application seeds permissions and the fixed risk action, but seeds no production risk type, pattern, keyword, or industry decision. Version 1 accepts only `equals_any` and `contains_any`; regex, scripts, SQL, URLs, templates, and dynamic expressions are rejected.

## Publication and immutable evidence

`subject_risk.catalog.publish` is the only activation path. Its supported, default, and minimum mode are all `two_person`. Successful execution creates an immutable `SubjectRiskCatalogRevision` containing a canonical snapshot and SHA-256 digest and advances the singleton catalog state. PostgreSQL requires the revision to reference an executed ApprovalRequest for that exact action. Draft edits never change the current published revision.

A SubjectVersion commit fails closed when no valid published revision exists. In the same PostgreSQL transaction it creates an immutable `SubjectRiskAssessment`, zero or more immutable `SubjectRiskHit` rows, and, when required, a pending `SubjectReview` plus requested event. The Assessment permanently references the revision used for classification. A later publication never reclassifies historical versions.

Feature enforcement is intentionally different: it resolves matched historical risk-type keys against the current valid published revision. This lets current policy tighten or relax feature permissions without rewriting the historical Assessment. Missing or corrupt current revision data fails closed.

## Review

Review list and detail use RBAC and CustomerAssignment `own`/`role`/`all` scope; an out-of-scope object is 404. Approve and reject use a complete secure administrator session, real CSRF, `subject_reviews.review`, `expected_version`, row locks, append-only ReviewEvent, Notification, and AuditEvent. They are direct single-administrator business decisions and do not create ApprovalRequest rows.

When a new SubjectVersion becomes current, only an older pending Review is superseded. Approved and rejected history remains unchanged. A stale review cannot authorize a non-current version. Responses contain safe reason categories but not field values, matched values, schema snapshots, rule patterns, digests, or audit payloads.

## API

- `GET/POST /api/v1/admin/subject-risk-types`
- `PATCH /api/v1/admin/subject-risk-types/{id}`
- `GET/POST /api/v1/admin/subject-risk-rules`
- `PATCH /api/v1/admin/subject-risk-rules/{id}`
- `GET /api/v1/admin/subject-risk-catalog`
- `POST /api/v1/admin/subject-risk-catalog/publish`
- `GET /api/v1/admin/subject-reviews`
- `GET /api/v1/admin/subject-reviews/{id}`
- `POST /api/v1/admin/subject-reviews/{id}/approve`
- `POST /api/v1/admin/subject-reviews/{id}/reject`

Subject detail exposes only `{status, review_id}` as its risk summary. All writes use the standard JSON envelope, X-Request-ID, simplified-Chinese errors, secure Session and CSRF boundaries.

## Migrations and rollback

Subjects migrations create the draft catalog, immutable revisions, assessments, hits, reviews, events, singleton state, and PostgreSQL guards. The RBAC migration seeds only permissions and the fixed two-person RiskAction/RiskPolicy. The data migration initializes an empty singleton state but does not publish a revision or fabricate risk history.

Trigger rollback removes database guards only; it does not make already-created evidence safe to rewrite. Reversing the schema migration deletes risk and review evidence and must not be used as a routine production rollback. Before any reverse migration, stop writes, review ApprovalRequest/AuditEvent references, and take a verified backup. Prefer a forward fix or backup restore. No Tencent Cloud database or moderation provider is connected by this task.

## Verification

Fast tests run with the normal backend and frontend suites. Real PostgreSQL/Redis verification runs through:

```powershell
.\scripts\test-subject-schema.ps1
```

The isolated Compose service includes `tests/test_subject_risk_postgres.py`, covering database guards, mandatory publication approval, concurrent exactly-once review decisions, current-version invalidation, `own`/`role`/`all` scope, and historical-classification/current-policy separation.