# XW-0418 — Semantic Scoring Orchestration

## Unit 2B scope

This unit wires the frozen DeepSeek semantic-scoring adapter into the scoring
pipeline without modifying the detected-model execution lifecycle.

The detection worker remains responsible only for:

- detected-model execution;
- immutable raw response;
- citation extraction;
- programmatic scoring facts;
- detection quota/settlement and terminal status.

Semantic scoring is a separate operation.

## Per-question flow

For an immutable successful `ModelResponse` that participates in scoring:

1. load its immutable `ProgrammaticScoreResult`;
2. build a `SemanticScoringPayload` from:
   - frozen question text/type;
   - immutable raw model response;
   - frozen subject version snapshot;
   - programmatic scoring context;
   - immutable citation evidence;
   - scoring-rule version;
3. resolve the DeepSeek `semantic_scoring` capability;
4. invoke the semantic adapter;
5. hash the normalized semantic output;
6. combine programmatic and semantic facts into `QuestionAggregationInput`;
7. run the XW-0418 deterministic aggregation core;
8. persist one immutable `score_results` row.

## Idempotency and concurrency

A sequential retry returns the existing `ScoreResult` without calling the
semantic provider again.

On PostgreSQL, semantic scoring for one `ModelResponse` is protected with a
session-level advisory lock keyed by the response id. This avoids two workers
calling the semantic provider concurrently for the same immutable response
without holding row locks or a database transaction open across the network
request.

The database uniqueness boundary remains the final persistence guard.

## Model-score finalization

`model_scores` is immutable, so a track is persisted only when:

- every planned participating detection call for that question type is terminal;
- every succeeded detection call for that type already has a `ScoreResult`.

Then:

- failed/cancelled detection calls are excluded from the model-score denominator;
- normal successful answers with no mention already have question score zero and
  remain in the denominator;
- natural and brand-directed tracks finalize independently;
- zero planned questions do not create a model-score row.

This prevents a partial model result from being frozen early.

## Scheduling surface

`due_semantic_score_response_ids()` returns succeeded, participating model
responses that have programmatic facts but no final score row.

A worker/scheduler can call `score_model_response()` for those ids. Provider
errors affect the scoring operation only; they never rewrite `ModelCall`,
`GeoDetectionModelRun`, or detection quota settlement state.

## Deferred

The remaining XW-0418 closure is:

- composite/report persistence surface if required by the report model;
- final boundary/full gate/PR closure.

XW-0419 exposure/competitor indexes remain out of scope.

Grade bands are now frozen in the deterministic aggregation core and are shared by model, GEO-composite, and brand-reputation scores.
