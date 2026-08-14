# XW-0207 Web import and SSRF protection

## Scope

XW-0207 imports public `HTTP/HTTPS` pages through an isolated `web_fetch` worker. It stores an
immutable, bounded text snapshot and requires an explicit user-confirmed parsed version before an
internal selector may return content. It does not execute JavaScript, load subresources, authenticate
to sites, upload objects, consume quota, invoke AI, or implement XW-0208.

## Network boundary

- URLs reject userinfo, fragments, controls, backslashes, zone identifiers, non-default ports and
  ambiguous numeric IP spellings. Hosts use pinned `idna` UTS46/STD3 normalization.
- Every A/AAAA answer must be globally routable. Loopback, private, link-local, multicast,
  documentation, reserved, IPv4-mapped bypasses and metadata addresses fail closed.
- The transport resolves once per hop, connects to an approved IP, preserves the original Host and
  TLS SNI, verifies TLS 1.2+ hostname trust, and verifies the actual peer IP. It never uses environment
  proxies.
- Redirects are manual, capped at five and fully revalidated. HTTPS-to-HTTP downgrade is rejected.
- The client sends GET plus fixed minimal headers, no Cookie, Authorization, Referer or user headers.
- Production defaults `WEB_IMPORT_ENABLED=false`; enabling also requires
  `WEB_IMPORT_NETWORK_POLICY_ENFORCED=true`. Private lab CIDRs exist only in the dedicated test
  settings and cannot be enabled by production configuration.

## Resource and parser limits

Connect/read/total deadlines default to 3/10/20 seconds. Headers are bounded by count, line and total
bytes; the decoded body is capped at 2 MiB and canonical text at 500,000 characters. Only identity
encoding and `text/html` or `text/plain` are accepted. Charset detection is bounded and limited to
UTF-8, GB18030 and Big5. The standard-library parser extracts title and visible text only; scripts,
styles, frames, objects and templates are ignored and never trigger secondary requests.

## Saga and immutable evidence

`WebSourceImport` is the durable Saga. API creation commits `queued` before enqueue; the dispatcher
recovers enqueue failures. Worker claims are short transactions, network I/O is outside transactions,
and finalization atomically writes `WebSourceSnapshot`, machine parsed version, pointers, event and
notification. Known transient failures persist bounded retry timing, known permanent failures become
terminal, and unknown failures use bounded Celery retries before terminal failure. Redis and task IDs
are not business facts.

PostgreSQL guards reject evidence update/delete, illegal terminal recovery, ownership mismatch,
non-contiguous parsed versions and invalid latest/confirmed pointers. Reversal of evidence migrations
requires review and backup; production should use forward fixes or backup restoration.

## Data exposure

The API returns a query-free display URL plus `has_query`; it never returns the canonical query,
resolved/peer addresses, raw headers, response digests, idempotency material or provenance internals.
Logs, events and notifications contain only IDs, stable codes and bounded metrics. Responses are
`no-store`, use Session/CSRF, owner-scoped 404 behavior, the standard envelope and request ID.

## Operations and validation

Run `scripts/test-web-import.ps1` or `scripts/test-web-import.sh`. The Compose overlay uses an internal
network with a fixed test-only CIDR, a static local HTTP lab, real PostgreSQL and Redis, and a real
Celery worker consuming only `web_fetch`. It has no route to the public Internet. The script removes
its isolated containers, network and volume on completion.

## Absolute deadline and CI execution hardening

The fetch transport uses one monotonic absolute deadline for the complete fetch, including all redirects. HTTP response parsing reads through a deadline-aware raw socket adapter that recalculates remaining time before every `recv_into`; each receive uses the smaller of the configured read timeout and the remaining total budget. Connect/TLS setup likewise cannot start once the shared budget is exhausted. Controlled lab tests exercise slow response headers, fixed-length body drip, chunked body drip, and cumulative redirect delay.

The isolated web-import acceptance scripts run long-lived dependencies first, execute migrations as a separate one-shot phase, then run `web-import-tests` as a distinct phase whose exit code gates the job. Cleanup remains unconditional. This prevents a successful migration container exit from stopping the actual web-import test container before pytest runs.
