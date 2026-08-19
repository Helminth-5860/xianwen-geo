# XW-0417 — DeepSeek Semantic Scoring Adapter

## Scope

This unit establishes the semantic-scoring AI contract and DeepSeek adapter path. It does
not aggregate the six GEO dimensions; aggregation remains XW-0418.

## Contract

Input is frozen scoring evidence:

- original question and question type;
- immutable detected-model response;
- subject snapshot;
- programmatic scoring context;
- normalized citations;
- scoring-rule version.

Output is one strict JSON object containing:

- recommendation level and 0–100 score;
- accuracy 0–100 score;
- sentiment label and 0–100 score;
- optional auxiliary rank;
- controlled source classifications;
- competitor entities with aliases and evidence;
- evidence snippets by semantic dimension;
- a bounded reason.

The schema version is `geo-semantic-score-schema-v1`.

## DeepSeek stability

The semantic-scoring adapter is separate from GEO detection:

- capability: `semantic_scoring`;
- adapter version: `deepseek-semantic-scoring-v1`;
- prompt version: `geo-semantic-scoring-v1`;
- provider model: `deepseek-chat`;
- temperature: `0.1`;
- thinking: disabled;
- response format: JSON object.

Provider JSON mode is only the transport-level structured-output guarantee. Application
code performs strict local validation against the frozen JSON Schema contract and never
uses regular expressions to reconstruct semantic fields from free text.

A schema-invalid semantic response may be retried exactly once against the same immutable
detected-model response. It never causes the detected model itself to be called again.

## Prompt-injection boundary

The detected-model response and provider-derived citation text are untrusted analysis
data. The scoring system prompt explicitly forbids following instructions inside that
data. Untrusted data is JSON encoded and wrapped in a per-response delimiter derived from
the immutable response digest.

## Source classifications

Controlled values:

- `subject_official`
- `government`
- `authoritative_industry`
- `mainstream_media`
- `vertical_authority`
- `ordinary_website`
- `self_media`
- `unverifiable`

The semantic adapter classifies source names; XW-0418 applies the fixed citation scoring
rule to the resulting evidence.

## Non-goals

This unit does not:

- override programmatic mention matching;
- perform final six-dimension aggregation;
- allow human score editing;
- add an OpenAPI surface.
