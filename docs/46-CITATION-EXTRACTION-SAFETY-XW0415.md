# XW-0415 — Citation extraction and safety

## Scope

This unit adds immutable normalized citation facts for GEO model responses.

- Provider `DetectionOutput.citations` are preferred.
- When structured citations are unavailable, raw response text is scanned conservatively for HTTP(S) URLs.
- URL canonicalization and SSRF/DNS validation reuse `apps.web_sources.url_security`.
- No HTTP fetch, redirect following, or page-body retrieval is performed.
- Unsafe or unresolved URLs fail closed and are not persisted as usable canonical URLs.
- Raw model response text remains immutable evidence and is never rewritten.
- Citation normalization occurs before the final database settlement transaction so DNS resolution does not hold row locks.
- Citation facts are persisted only when the immutable `ModelResponse` is first created.

## Non-goals

- XW-0416 programmatic scoring
- XW-0417 DeepSeek semantic scoring
- XW-0418 score aggregation
- source-content fetching
