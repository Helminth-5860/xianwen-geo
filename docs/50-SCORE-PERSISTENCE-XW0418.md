# XW-0418 — Immutable Score Persistence

## Unit 2A scope

This unit persists the deterministic score facts established by XW-0418 Unit 1.
It intentionally does not execute DeepSeek from the detection settlement worker.

The detection worker stores the immutable raw response, citation evidence, and
programmatic facts only. Semantic scoring remains a separate scoring-pipeline
operation so that provider failure cannot rewrite the success/failure semantics
of the detected-model call.

## `score_results`

One immutable row per `ModelResponse`.

It stores:

- question type and score track;
- the six dimension scores, with mention/rank nullable for brand-directed questions;
- total question score;
- scoring-rule version;
- semantic schema/provider/model/adapter/prompt/provider-model provenance;
- semantic output digest;
- combined programmatic and semantic evidence.

The row is append-only in Django and protected by a PostgreSQL UPDATE/DELETE
trigger.

## `model_scores`

One immutable row per detection model run and score track.

It stores:

- planned and successful question counts;
- success rate;
- formal/reference/not-generated status;
- model score;
- scoring-rule version.

The `(model_run, track)` pair is unique. PostgreSQL rejects UPDATE/DELETE.

## Idempotency

Persistence uses the database uniqueness boundary plus `get_or_create`.
A repeated request with identical immutable facts returns the existing row.
A repeated request with different facts fails closed with
`ScorePersistenceConflict`; it never updates historical scoring evidence.

## Deferred

The next XW-0418 unit wires the already-tested DeepSeek semantic adapter into a
dedicated scoring orchestration path and then calls these persistence helpers.
That orchestration must remain separate from `execute_model_call`.
