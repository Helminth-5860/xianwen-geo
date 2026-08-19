# XW-0416 — Programmatic scoring foundation

## Scope

This unit persists immutable deterministic scoring facts for each successful GEO model response.

### Program-first rules

- Exact subject official-name, alias, English-name, and confirmed unique-product matching.
- Explicit numbered/list rank detection.
- Citation base evidence.
- Natural questions with no subject mention receive mention score `0` and deterministic rank score `0`.
- Brand-directed questions keep mention/rank as not applicable.
- Unstructured rank interpretation is deferred to XW-0417 semantic scoring.

### Rank mapping

- #1 -> 100
- #2-3 -> 80
- #4-5 -> 60
- #6-10 -> 40
- >10 -> 20

### Citation boundary

This unit does not invent final source-quality classification. Safe citations require semantic source-name classification in XW-0417. No-citation is deterministic `0`; unresolved or identifiable source-without-URL evidence can use the documented `20` floor. Invalid/blocked-only URLs remain `0` so unsafe input cannot earn citation credit.

## Persistence

`ProgrammaticScoreResult` is immutable evidence. XW-0417 semantic results must be stored separately; XW-0418 later aggregates final six-dimension scores.
