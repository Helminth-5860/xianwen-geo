from __future__ import annotations

import uuid
from dataclasses import dataclass

from .distillation_contracts import DistillationKeywordInput, DistillationResponse
from .distillation_exceptions import DistillationInvalidResponse, DistillationValuesInvalid
from .normalization import KeywordNormalizationError, normalize_plain_text

ACTIONS = {"keep", "merge", "delete", "low_value"}


@dataclass(frozen=True)
class NormalizedDistillationItem:
    source_keyword_id: uuid.UUID
    action: str
    canonical_keyword_id: uuid.UUID | None
    merge_group_key: uuid.UUID | None
    reason: str

    def payload(self) -> dict[str, object]:
        return {
            "source_keyword_id": str(self.source_keyword_id),
            "action": self.action,
            "canonical_keyword_id": (
                str(self.canonical_keyword_id) if self.canonical_keyword_id else None
            ),
            "merge_group_key": str(self.merge_group_key) if self.merge_group_key else None,
            "reason": self.reason,
        }


def _uuid(value, *, required: bool) -> uuid.UUID | None:
    if value in (None, "") and not required:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise DistillationInvalidResponse from exc


def _reason(value) -> str:
    if not isinstance(value, str):
        raise DistillationInvalidResponse
    try:
        normalized, _ = normalize_plain_text(value, max_length=1000)
    except KeywordNormalizationError as exc:
        raise DistillationInvalidResponse from exc
    return normalized


def _validate_merge_groups(items, input_map, error_type):
    groups: dict[uuid.UUID, list[NormalizedDistillationItem]] = {}
    for item in items:
        if item.action == "merge":
            assert item.merge_group_key is not None
            groups.setdefault(item.merge_group_key, []).append(item)
    for members in groups.values():
        source_ids = {item.source_keyword_id for item in members}
        canonical_ids = {item.canonical_keyword_id for item in members}
        if len(members) < 2 or len(canonical_ids) != 1:
            raise error_type
        canonical_id = next(iter(canonical_ids))
        if canonical_id not in source_ids:
            raise error_type
        signatures = {
            (
                input_map[item.source_keyword_id].is_regional,
                input_map[item.source_keyword_id].region_matching_key,
            )
            for item in members
        }
        if len(signatures) != 1:
            raise error_type


def validate_provider_response(
    *, inputs: tuple[DistillationKeywordInput, ...], response: DistillationResponse
) -> list[NormalizedDistillationItem]:
    input_map = {uuid.UUID(item.id): item for item in inputs}
    if len(input_map) != len(inputs) or len(response.items) != len(inputs):
        raise DistillationInvalidResponse
    normalized = []
    seen = set()
    for item in response.items:
        source_id = _uuid(item.source_keyword_id, required=True)
        assert source_id is not None
        if source_id not in input_map or source_id in seen or item.action not in ACTIONS:
            raise DistillationInvalidResponse
        seen.add(source_id)
        is_merge = item.action == "merge"
        canonical_id = _uuid(item.canonical_keyword_id, required=is_merge)
        group_key = _uuid(item.merge_group_key, required=is_merge)
        if not is_merge and (canonical_id is not None or group_key is not None):
            raise DistillationInvalidResponse
        normalized.append(
            NormalizedDistillationItem(
                source_keyword_id=source_id,
                action=item.action,
                canonical_keyword_id=canonical_id,
                merge_group_key=group_key,
                reason=_reason(item.reason),
            )
        )
    if seen != set(input_map):
        raise DistillationInvalidResponse
    _validate_merge_groups(normalized, input_map, DistillationInvalidResponse)
    return normalized


def validate_user_adjustments(*, inputs, ai_items, items):
    input_map = {uuid.UUID(item.id): item for item in inputs}
    ai_map = {uuid.UUID(str(item["source_keyword_id"])): item for item in ai_items}
    if len(items) != len(input_map) or set(ai_map) != set(input_map):
        raise DistillationValuesInvalid
    normalized = []
    seen = set()
    for raw in items:
        try:
            source_id = uuid.UUID(str(raw["source_keyword_id"]))
            action = raw["action"]
        except (KeyError, TypeError, ValueError) as exc:
            raise DistillationValuesInvalid from exc
        if source_id not in input_map or source_id in seen or action not in ACTIONS:
            raise DistillationValuesInvalid
        seen.add(source_id)
        is_merge = action == "merge"
        try:
            canonical_id = _uuid(raw.get("canonical_keyword_id"), required=is_merge)
            group_key = _uuid(raw.get("merge_group_key"), required=is_merge)
        except DistillationInvalidResponse as exc:
            raise DistillationValuesInvalid from exc
        if not is_merge and (canonical_id is not None or group_key is not None):
            raise DistillationValuesInvalid
        user_reason = raw.get("user_reason", "")
        if not isinstance(user_reason, str):
            raise DistillationValuesInvalid
        if user_reason:
            try:
                user_reason, _ = normalize_plain_text(user_reason, max_length=1000)
            except KeywordNormalizationError as exc:
                raise DistillationValuesInvalid from exc
        ai = ai_map[source_id]
        normalized.append(
            {
                "source_keyword_id": source_id,
                "action": action,
                "canonical_keyword_id": canonical_id,
                "merge_group_key": group_key,
                "ai_action": ai["action"],
                "ai_canonical_keyword_id": (
                    uuid.UUID(str(ai["canonical_keyword_id"]))
                    if ai.get("canonical_keyword_id")
                    else None
                ),
                "ai_merge_group_key": (
                    uuid.UUID(str(ai["merge_group_key"])) if ai.get("merge_group_key") else None
                ),
                "ai_reason": ai["reason"],
                "user_reason": user_reason,
                "user_overridden": (
                    action != ai["action"]
                    or str(canonical_id or "") != str(ai.get("canonical_keyword_id") or "")
                    or str(group_key or "") != str(ai.get("merge_group_key") or "")
                    or bool(user_reason)
                ),
            }
        )
    if seen != set(input_map):
        raise DistillationValuesInvalid
    typed = [
        NormalizedDistillationItem(
            source_keyword_id=item["source_keyword_id"],
            action=item["action"],
            canonical_keyword_id=item["canonical_keyword_id"],
            merge_group_key=item["merge_group_key"],
            reason=item["ai_reason"],
        )
        for item in normalized
    ]
    _validate_merge_groups(typed, input_map, DistillationValuesInvalid)
    return normalized
