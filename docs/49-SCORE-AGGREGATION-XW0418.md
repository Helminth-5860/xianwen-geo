# XW-0418 — Score Aggregation Core

## Unit 1 scope

This unit freezes the deterministic aggregation core only. It does not yet add
database persistence, semantic-provider orchestration, report generation, or the
grade display table.

The purpose of separating this core is to keep the scoring mathematics testable
without coupling it to Celery, provider retries, or Django transactions.

## Natural exploration question

The six dimensions are scored from 0 to 100 with frozen weights:

- mention: 25%
- recommendation: 20%
- rank: 15%
- accuracy: 20%
- sentiment: 10%
- citation: 10%

If the subject is not mentioned, the whole question total is zero.

Programmatic mention facts remain authoritative. Semantic scoring cannot infer a
missing mention.

## Brand-directed question

Mention and rank are N/A. The remaining four dimensions are re-normalized using
their original relative weights:

- recommendation: 20 / 60
- accuracy: 20 / 60
- sentiment: 10 / 60
- citation: 10 / 60

The result belongs to the `brand_reputation` track and never enters the GEO track.

## Frozen semantic-to-program mappings

Recommendation is derived from the semantic level:

- strong recommendation: 100
- recommendation/listed: 75
- neutral/objective: 40
- discouraged/strongly discouraged: 0

Accuracy must use the frozen 100/75/40/0 scale.

Sentiment must use the frozen 100/75/50/25/0 scale.

For semantic rank assistance:

- 1: 100
- 2–3: 80
- 4–5: 60
- 6–10: 40
- >10: 20
- mentioned in body but no ranked recommendation position: 10

Citation classification:

- subject official / government / authoritative industry: 100
- mainstream media / authoritative vertical: 80
- ordinary website / self-media: 50
- unverifiable: 20
- deterministic no-source or blocked evidence remains the programmatic 0/20 fact

When multiple valid sources exist, the highest-quality valid source is used.

## Model score

Within one model and one question type:

`model_score = sum(successful question scores) / successful question count`

All questions are equal weight.

A normal answer that does not mention the subject remains a successful question
with score zero. Provider failure, timeout, or cancellation is excluded from the
denominator.

`success_rate = successful question count / planned question count * 100`

- success rate >= 80%: formal model score
- success rate < 80%: reference model score
- zero planned questions: no score for that track

Natural and brand-directed questions produce separate model tracks.

## Composite score

Only formal model scores enter the composite average.

- 6–8 formal models: formal composite
- 1–5 formal models: reference composite
- 0 formal models: failed track

Failed or reference model scores are not inserted as zero into the composite.

## Precision

All persisted score values will use at least four decimal places. Unit 1 uses
Decimal arithmetic and stores the deterministic domain result at four decimal
places.

## Grade bands

The frozen score grade table is shared by model scores, GEO composite scores,
and brand-reputation scores:

- 90–100: 卓越
- 75–<90: 优秀
- 60–<75: 一般
- 40–<60: 较弱
- 0–<40: 薄弱

The implementation uses contiguous lower-bound thresholds (`90`, `75`, `60`,
`40`) so four-decimal persisted scores have no gaps between the document's
display ranges.

## Deferred to the next XW-0418 unit

- immutable `score_results` / `model_scores` persistence;
- semantic scoring invocation and idempotent orchestration;
- PostgreSQL immutability guards;
- integration with report generation.
