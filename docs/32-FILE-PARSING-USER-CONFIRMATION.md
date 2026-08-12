# XW-0206 File parsing and user confirmation

## Frozen facts

Only an immutable, completed and clean `DocumentVersion` can enter parsing. Parsing does not
change the file, create a `FileStorageAllocation`, or consume a new quota. PostgreSQL is the
source of truth for jobs, parsed versions, current pointers, retries and events.

`DocumentParseJob` persists `queued -> running -> retry_wait|succeeded|failed`. Only permanent
content/security errors become `failed`; storage, OCR and infrastructure outages remain
`retry_wait` with a durable next attempt. A raw idempotency key is never stored.

A successful machine parse creates version 1. User confirmation creates a continuous immutable
chain. It can edit canonical text only; tables and warning codes are projected from the immutable
machine base. Identical confirmation replay returns the existing fact without another event or
state-version increment.

## Parsers and providers

The static registry supports PDF, DOCX, XLSX, UTF-8 TXT/Markdown and JPEG/PNG/WEBP OCR. It never
uses dynamic import, shell execution, URL fetch, external relationships, macros, embedded
executables or PDF actions. Scanned PDFs do not silently fall back to OCR.

`MockOcrProvider` is local/test only. Production permits `unavailable` until a separately
reviewed real adapter exists; image parse returns a generic 503 before a job is created. This
project does not claim a production OCR integration.

## APIs and permissions

- `POST /api/v1/documents/{document_id}/parse`: owner, writable approved account, draft/active
  Subject, effective Subscription, CSRF and Idempotency-Key.
- `GET /api/v1/documents/{document_id}/parse-result`: owner-scoped and fully read-only.
- `POST /api/v1/documents/{document_id}/confirm`: owner and normal Subject-edit eligibility;
  an effective Subscription is not required, but archived/cancel-pending/frozen/cancelled writes
  are rejected.

All responses use the standard envelope and `Cache-Control: no-store`. They never expose object
keys, file hashes, content/idempotency digests, task IDs, generations, raw exceptions or OCR
payloads. Confirmed content is not automatically approved for AI; downstream callers must use
the feature-aware selector, which re-applies the XW-0204 risk guard.

## Worker and retry boundary

Untrusted file parsing runs on the dedicated `file_processing` queue. The Compose worker runs
as the non-root application user with a read-only root filesystem, bounded no-exec tmpfs,
dropped capabilities, low prefetch/resource limits and an internal-only network to PostgreSQL,
Redis and private MinIO. The API does not parse file bytes.

The worker claims in a short transaction, streams private storage and parses outside a database
transaction, then finalizes in a short transaction. PostgreSQL terminal facts make redelivery
exactly-once. Beat only scans durable `retry_wait` rows and queues IDs.
It also requeues `running` jobs only after the configured durable lease expires; a new generation
invalidates late results from a lost worker without using Redis or task IDs as business truth.

## Migrations and rollback

Migrations create no parse or confirmation history for existing files. PostgreSQL triggers reject
ownership mismatch, invalid state transitions, sequence gaps, pointer rollback and UPDATE/DELETE
of immutable versions/events. Reversing the guard migration with parsed evidence deliberately
fails; production recovery requires reviewed forward repair or backup restoration.

## Explicit non-goals

No XW-0207 web import/SSRF, AI enrichment, keyword/GEO work, file replacement/deletion,
DOC/XLS, scanned-PDF OCR fallback, public file URL, Subject quota, parsing quota or production
OCR provider is implemented.
