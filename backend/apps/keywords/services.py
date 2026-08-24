from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.plans.models import Subscription
from apps.subjects.models import Subject, SubjectVersion
from apps.subjects.subject_services import subject_for_user_or_404
from apps.users.models import User

from .exceptions import (
    KeywordAccountUnavailable,
    KeywordPlanRequired,
    KeywordStateConflict,
    KeywordSubjectVersionConflict,
    KeywordValuesInvalid,
    KeywordVersionConflict,
    KeywordVersionNoChanges,
)
from .models import Keyword, KeywordDraftItem, KeywordSet, KeywordSetVersion
from .normalization import (
    KeywordNormalizationError,
    NormalizedKeyword,
    keyword_content_digest,
    normalize_keyword_items,
    normalize_plain_text,
    resolve_base_keyword_indexes,
)


@dataclass(frozen=True)
class KeywordWriteState:
    can_write: bool
    reason: str


def keyword_write_state(*, user: User, subject: Subject) -> KeywordWriteState:
    if not user.is_active or user.account_status != User.AccountStatus.ACTIVE:
        return KeywordWriteState(False, "account_unavailable")
    if subject.status == Subject.Status.ARCHIVED:
        return KeywordWriteState(False, "subject_archived")
    if subject.current_version_id is None:
        return KeywordWriteState(False, "subject_version_required")
    now = timezone.now()
    if not Subscription.objects.filter(
        user=user,
        status=Subscription.Status.ACTIVE,
        starts_at__lte=now,
        ends_at__gt=now,
    ).exists():
        return KeywordWriteState(False, "plan_required")
    return KeywordWriteState(True, "")


def _assert_user_write_allowed(user: User) -> None:
    if not user.is_active or user.account_status != User.AccountStatus.ACTIVE:
        raise KeywordAccountUnavailable


def _lock_effective_subscription(user: User) -> Subscription:
    now = timezone.now()
    row = (
        Subscription.objects.select_for_update()
        .filter(
            user=user,
            status=Subscription.Status.ACTIVE,
            starts_at__lte=now,
            ends_at__gt=now,
        )
        .order_by("starts_at", "id")
        .first()
    )
    if row is None:
        raise KeywordPlanRequired
    return row


def _lock_subject_for_keywords(
    *, user: User, subject_id, expected_subject_version_id
) -> tuple[Subject, SubjectVersion]:
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    if subject.status == Subject.Status.ARCHIVED:
        raise KeywordStateConflict
    if subject.current_version_id is None:
        raise KeywordSubjectVersionConflict
    if str(subject.current_version_id) != str(expected_subject_version_id):
        raise KeywordSubjectVersionConflict
    current_version = SubjectVersion.objects.select_for_update().get(
        pk=subject.current_version_id,
        subject=subject,
    )
    return subject, current_version


def keyword_set_for_user_or_404(*, user: User, subject_id, lock: bool = False) -> KeywordSet:
    query = KeywordSet.objects.filter(user=user, subject_id=subject_id)
    if lock:
        query = query.select_for_update()
    try:
        return query.get()
    except KeywordSet.DoesNotExist as exc:
        raise NotFound from exc


def keyword_set_for_subject(*, user: User, subject: Subject) -> KeywordSet | None:
    return (
        KeywordSet.objects.filter(user=user, subject=subject)
        .select_related("draft_subject_version", "current_version")
        .first()
    )


def _normalized_from_draft(row: KeywordDraftItem) -> NormalizedKeyword:
    return NormalizedKeyword(
        text=row.text,
        matching_text=row.matching_text,
        structure_type=row.structure_type,
        is_regional=row.is_regional,
        region_level=row.region_level,
        region_text=row.region_text,
        region_matching_key=row.region_matching_key,
        base_keyword_text=row.base_keyword_text,
        base_keyword_matching=(
            normalize_plain_text(row.base_keyword_text)[1] if row.base_keyword_text else None
        ),
        business_category=row.business_category,
        search_intent=row.search_intent,
        relevance_score=row.relevance_score,
        priority=row.priority,
        ai_reason=row.ai_reason,
        sort_order=row.sort_order,
    )


def _draft_payload(keyword_set: KeywordSet) -> list[dict[str, object]]:
    return [
        _normalized_from_draft(row).semantic_payload()
        for row in keyword_set.draft_items.order_by("sort_order", "id")
    ]


def _new_payload(items: list[NormalizedKeyword]) -> list[dict[str, object]]:
    return [item.semantic_payload() for item in items]


def _replace_draft_rows(keyword_set: KeywordSet, items: list[NormalizedKeyword]) -> None:
    keyword_set.draft_items.all().delete()
    KeywordDraftItem.objects.bulk_create(
        [
            KeywordDraftItem(
                keyword_set=keyword_set,
                text=item.text,
                matching_text=item.matching_text,
                structure_type=item.structure_type,
                is_regional=item.is_regional,
                region_level=item.region_level,
                region_text=item.region_text,
                region_matching_key=item.region_matching_key,
                base_keyword_text=item.base_keyword_text,
                business_category=item.business_category,
                search_intent=item.search_intent,
                relevance_score=item.relevance_score,
                priority=item.priority,
                ai_reason=item.ai_reason,
                sort_order=item.sort_order,
            )
            for item in items
        ]
    )


@transaction.atomic
def save_keyword_draft(
    *,
    user_id,
    subject_id,
    expected_version: int,
    expected_subject_version_id,
    items: list[dict[str, object]],
) -> tuple[KeywordSet, bool]:
    user = User.objects.select_for_update().get(pk=user_id)
    _assert_user_write_allowed(user)
    subject, subject_version = _lock_subject_for_keywords(
        user=user,
        subject_id=subject_id,
        expected_subject_version_id=expected_subject_version_id,
    )
    _lock_effective_subscription(user)
    try:
        normalized = normalize_keyword_items(items)
    except KeywordNormalizationError as exc:
        raise KeywordValuesInvalid from exc

    keyword_set = KeywordSet.objects.select_for_update().filter(subject=subject).first()
    if keyword_set is None:
        if expected_version != 0:
            raise KeywordVersionConflict
        try:
            keyword_set = KeywordSet.objects.create(
                user=user,
                subject=subject,
                draft_subject_version=subject_version,
                version=1,
            )
        except IntegrityError as exc:
            raise KeywordVersionConflict from exc
        _replace_draft_rows(keyword_set, normalized)
        return keyword_set, True

    if keyword_set.user_id != user.pk or keyword_set.version != expected_version:
        raise KeywordVersionConflict
    current_payload = _draft_payload(keyword_set)
    new_payload = _new_payload(normalized)
    if (
        keyword_set.draft_subject_version_id == subject_version.pk
        and current_payload == new_payload
    ):
        return keyword_set, False

    _replace_draft_rows(keyword_set, normalized)
    keyword_set.draft_subject_version = subject_version
    keyword_set.version += 1
    keyword_set.save(update_fields=["draft_subject_version", "version", "updated_at"])
    return keyword_set, True


def replace_keyword_draft_from_generation(
    *,
    user_id,
    subject_id,
    expected_version: int,
    expected_subject_version_id,
    items: list[dict[str, object]],
) -> KeywordSet:
    keyword_set, changed = save_keyword_draft(
        user_id=user_id,
        subject_id=subject_id,
        expected_version=expected_version,
        expected_subject_version_id=expected_subject_version_id,
        items=items,
    )
    if not changed:
        raise KeywordVersionNoChanges
    return keyword_set


@transaction.atomic
def commit_keyword_version(
    *,
    user_id,
    subject_id,
    expected_version: int,
    expected_subject_version_id,
) -> tuple[KeywordSet, KeywordSetVersion]:
    user = User.objects.select_for_update().get(pk=user_id)
    _assert_user_write_allowed(user)
    subject, subject_version = _lock_subject_for_keywords(
        user=user,
        subject_id=subject_id,
        expected_subject_version_id=expected_subject_version_id,
    )
    _lock_effective_subscription(user)
    try:
        keyword_set = KeywordSet.objects.select_for_update().get(subject=subject, user=user)
    except KeywordSet.DoesNotExist as exc:
        raise KeywordValuesInvalid from exc
    if keyword_set.version != expected_version:
        raise KeywordVersionConflict
    if keyword_set.draft_subject_version_id != subject_version.pk:
        raise KeywordSubjectVersionConflict
    draft_rows = list(keyword_set.draft_items.order_by("sort_order", "id"))
    if not draft_rows:
        raise KeywordValuesInvalid
    normalized = [_normalized_from_draft(row) for row in draft_rows]
    digest = keyword_content_digest(subject_version_id=subject_version.pk, items=normalized)
    current = keyword_set.current_version
    if (
        current is not None
        and current.subject_version_id == subject_version.pk
        and current.content_digest == digest
    ):
        raise KeywordVersionNoChanges
    next_version = 1 if current is None else current.version_no + 1
    version = KeywordSetVersion.objects.create(
        keyword_set=keyword_set,
        user=user,
        subject=subject,
        subject_version=subject_version,
        version_no=next_version,
        content_digest=digest,
        item_count=len(normalized),
        created_by=user,
    )
    try:
        base_indexes = resolve_base_keyword_indexes(normalized)
    except KeywordNormalizationError as exc:
        raise KeywordValuesInvalid from exc
    keyword_ids = [uuid.uuid4() for _ in normalized]
    Keyword.objects.bulk_create(
        [
            Keyword(
                id=keyword_ids[index],
                keyword_set_version=version,
                text=item.text,
                matching_text=item.matching_text,
                structure_type=item.structure_type,
                is_regional=item.is_regional,
                region_level=item.region_level,
                region_text=item.region_text,
                region_matching_key=item.region_matching_key,
                base_keyword_id=(
                    keyword_ids[base_indexes[index]] if index in base_indexes else None
                ),
                business_category=item.business_category,
                search_intent=item.search_intent,
                relevance_score=item.relevance_score,
                priority=item.priority,
                ai_reason=item.ai_reason,
                sort_order=item.sort_order,
            )
            for index, item in enumerate(normalized)
        ]
    )
    keyword_set.current_version = version
    keyword_set.version += 1
    keyword_set.save(update_fields=["current_version", "version", "updated_at"])
    return keyword_set, version


def keyword_versions_for_user(*, user: User, subject_id):
    if not Subject.objects.filter(pk=subject_id, user=user).exists():
        raise NotFound
    return (
        KeywordSetVersion.objects.filter(user=user, subject_id=subject_id)
        .select_related("subject_version")
        .order_by("-version_no", "id")
    )


def keyword_version_for_user_or_404(*, user: User, subject_id, version_id) -> KeywordSetVersion:
    try:
        return (
            KeywordSetVersion.objects.filter(user=user, subject_id=subject_id)
            .select_related("subject_version")
            .prefetch_related("keywords")
            .get(pk=version_id)
        )
    except KeywordSetVersion.DoesNotExist as exc:
        raise NotFound from exc
