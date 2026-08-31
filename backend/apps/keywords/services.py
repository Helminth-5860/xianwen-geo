from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

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
from .models import (
    DistillationWorkspace,
    Keyword,
    KeywordAssetPreference,
    KeywordDraftItem,
    KeywordSet,
    KeywordSetVersion,
)
from .normalization import (
    KeywordNormalizationError,
    NormalizedKeyword,
    keyword_content_digest,
    normalize_keyword_items,
    normalize_plain_text,
    normalize_region_entries,
    resolve_base_keyword_indexes,
)
from .taxonomy import normalize_category, normalize_intents


@dataclass(frozen=True)
class KeywordWriteState:
    can_write: bool
    reason: str


@dataclass(frozen=True)
class KeywordAssetGroup:
    core_keyword: Keyword
    related_keywords: tuple[Keyword, ...]
    preference: KeywordAssetPreference | None


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
    subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    query = KeywordSet.objects.filter(subject=subject)
    if lock:
        query = query.select_for_update()
    try:
        return query.get()
    except KeywordSet.DoesNotExist as exc:
        raise NotFound from exc


def keyword_set_for_subject(*, user: User, subject: Subject) -> KeywordSet | None:
    subject_for_user_or_404(user=user, subject_id=subject.pk)
    return (
        KeywordSet.objects.filter(subject=subject)
        .select_related("draft_subject_version", "current_version")
        .first()
    )


def _normalized_from_draft(row: KeywordDraftItem) -> NormalizedKeyword:
    base_keyword_text = row.base_keyword_text
    base_keyword_matching = (
        normalize_plain_text(base_keyword_text)[1] if base_keyword_text else None
    )
    # Historical drafts could persist the keyword itself as its base keyword.
    # Treat that legacy shape as no base relationship so it cannot block a later
    # generated version from being committed.
    if base_keyword_matching == row.matching_text:
        base_keyword_text = None
        base_keyword_matching = None
    return NormalizedKeyword(
        text=row.text,
        matching_text=row.matching_text,
        structure_type=row.structure_type,
        is_regional=row.is_regional,
        region_level=row.region_level,
        region_text=row.region_text,
        region_matching_key=row.region_matching_key,
        base_keyword_text=base_keyword_text,
        base_keyword_matching=base_keyword_matching,
        business_category=row.business_category,
        search_intent=row.search_intent,
        search_intents=tuple(row.search_intents),
        regions=tuple(row.regions),
        source=row.source,
        notes=row.notes,
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
                search_intents=list(item.search_intents),
                regions=list(item.regions),
                source=item.source,
                notes=item.notes,
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
def append_keyword_draft_items(
    *,
    user_id,
    subject_id,
    expected_version: int,
    expected_subject_version_id,
    items: list[dict[str, object]],
) -> tuple[KeywordSet, int, list[str]]:
    """Append candidate keywords without replacing candidates from another source."""

    user = User.objects.select_for_update().get(pk=user_id)
    _assert_user_write_allowed(user)
    subject, subject_version = _lock_subject_for_keywords(
        user=user,
        subject_id=subject_id,
        expected_subject_version_id=expected_subject_version_id,
    )
    _lock_effective_subscription(user)
    additions = []
    try:
        for raw_item in items:
            additions.append(normalize_keyword_items([raw_item])[0])
    except (IndexError, KeywordNormalizationError) as exc:
        raise KeywordValuesInvalid from exc

    keyword_set = KeywordSet.objects.select_for_update().filter(subject=subject).first()
    actual_version = keyword_set.version if keyword_set is not None else 0
    if actual_version != expected_version:
        raise KeywordVersionConflict

    existing = (
        [
            _normalized_from_draft(row)
            for row in keyword_set.draft_items.order_by("sort_order", "id")
        ]
        if keyword_set is not None
        else []
    )
    seen = {(item.matching_text, item.region_matching_key) for item in existing}
    appended: list[NormalizedKeyword] = []
    skipped: list[str] = []
    for item in additions:
        key = (item.matching_text, item.region_matching_key)
        if key in seen:
            skipped.append(item.text)
            continue
        seen.add(key)
        appended.append(replace(item, sort_order=len(existing) + len(appended)))
    if not appended:
        if keyword_set is None:
            raise KeywordValuesInvalid
        return keyword_set, 0, skipped

    if keyword_set is None:
        try:
            keyword_set = KeywordSet.objects.create(
                user=user,
                subject=subject,
                draft_subject_version=subject_version,
                version=1,
            )
        except IntegrityError as exc:
            raise KeywordVersionConflict from exc
    else:
        keyword_set.draft_subject_version = subject_version
        keyword_set.version += 1
        keyword_set.save(update_fields=["draft_subject_version", "version", "updated_at"])
    _replace_draft_rows(keyword_set, [*existing, *appended])
    return keyword_set, len(appended), skipped


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
        keyword_set = KeywordSet.objects.select_for_update().get(subject=subject)
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
                search_intents=list(item.search_intents),
                regions=list(item.regions),
                source=item.source,
                notes=item.notes,
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
    subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    return (
        KeywordSetVersion.objects.filter(subject=subject)
        .select_related("subject_version")
        .order_by("-version_no", "id")
    )


def keyword_version_for_user_or_404(*, user: User, subject_id, version_id) -> KeywordSetVersion:
    subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    try:
        return (
            KeywordSetVersion.objects.filter(subject=subject)
            .select_related("subject_version")
            .prefetch_related("keywords")
            .get(pk=version_id)
        )
    except KeywordSetVersion.DoesNotExist as exc:
        raise NotFound from exc


def _current_asset_keywords(*, user: User, subject: Subject) -> dict[uuid.UUID, Keyword]:
    workspace = (
        DistillationWorkspace.objects.filter(subject=subject)
        .select_related("current_set")
        .first()
    )
    if workspace is None or workspace.current_set_id is None:
        return {}
    rows = workspace.current_set.items.select_related(
        "source_keyword", "canonical_keyword"
    ).order_by("sort_order", "id")
    output: dict[uuid.UUID, Keyword] = {}
    for row in rows:
        keyword = (
            row.source_keyword
            if row.action == "keep"
            else row.canonical_keyword
            if row.action == "merge"
            else None
        )
        if keyword is not None:
            output.setdefault(keyword.pk, keyword)
    return output


def _current_asset_groups(
    *, user: User, subject: Subject
) -> list[tuple[Keyword, tuple[Keyword, ...]]]:
    workspace = (
        DistillationWorkspace.objects.filter(subject=subject)
        .select_related("current_set")
        .first()
    )
    if workspace is None or workspace.current_set_id is None:
        return []
    rows = workspace.current_set.items.select_related(
        "source_keyword", "canonical_keyword"
    ).order_by("sort_order", "id")
    groups: dict[uuid.UUID, tuple[Keyword, list[Keyword]]] = {}
    related_ids: dict[uuid.UUID, set[uuid.UUID]] = {}
    for row in rows:
        core_keyword = (
            row.source_keyword
            if row.action == "keep"
            else row.canonical_keyword
            if row.action == "merge"
            else None
        )
        if core_keyword is None:
            continue
        group = groups.setdefault(core_keyword.pk, (core_keyword, []))
        if row.action != "merge" or row.source_keyword_id == core_keyword.pk:
            continue
        seen = related_ids.setdefault(core_keyword.pk, set())
        if row.source_keyword_id not in seen:
            group[1].append(row.source_keyword)
            seen.add(row.source_keyword_id)
    return [(core, tuple(related)) for core, related in groups.values()]


def keyword_assets_for_user(*, user: User, subject_id):
    subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    groups = _current_asset_groups(user=user, subject=subject)
    core_ids = [core.pk for core, _ in groups]
    preferences = {
        row.source_keyword_id: row
        for row in KeywordAssetPreference.objects.filter(
            user=user,
            subject=subject,
            source_keyword_id__in=core_ids,
        )
    }
    return subject, [
        KeywordAssetGroup(
            core_keyword=core,
            related_keywords=related,
            preference=preferences.get(core.pk),
        )
        for core, related in groups
    ]


@transaction.atomic
def update_keyword_asset_preference(
    *, user_id, subject_id, keyword_id, values: dict[str, object]
) -> KeywordAssetPreference:
    user = User.objects.select_for_update().get(pk=user_id)
    _assert_user_write_allowed(user)
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    if subject.status == Subject.Status.ARCHIVED:
        raise KeywordStateConflict
    _lock_effective_subscription(user)
    assets = _current_asset_keywords(user=user, subject=subject)
    keyword = assets.get(uuid.UUID(str(keyword_id)))
    if keyword is None:
        raise NotFound
    preference, _ = KeywordAssetPreference.objects.select_for_update().get_or_create(
        user=user,
        subject=subject,
        source_keyword=keyword,
    )
    update_fields = []
    if "display_text" in values:
        raw = values["display_text"]
        if raw:
            try:
                preference.display_text = normalize_plain_text(str(raw))[0]
            except KeywordNormalizationError as exc:
                raise KeywordValuesInvalid from exc
        else:
            preference.display_text = ""
        update_fields.append("display_text")
    if "category" in values:
        raw = values["category"]
        try:
            preference.business_category = normalize_category(raw) if raw else ""
        except ValueError as exc:
            raise KeywordValuesInvalid from exc
        update_fields.append("business_category")
    if "intents" in values:
        try:
            preference.search_intents = (
                list(normalize_intents(values["intents"])) if values["intents"] else []
            )
        except ValueError as exc:
            raise KeywordValuesInvalid from exc
        update_fields.append("search_intents")
    if "regions" in values:
        try:
            preference.region_selections = normalize_region_entries(values["regions"])
        except KeywordNormalizationError as exc:
            raise KeywordValuesInvalid from exc
        update_fields.append("region_selections")
    for field in ("enabled", "usable_for_questions"):
        if field in values:
            setattr(preference, field, values[field])
            update_fields.append(field)
    if "deleted" in values:
        preference.deleted_at = timezone.now() if values["deleted"] else None
        update_fields.append("deleted_at")
        if values["deleted"]:
            preference.enabled = False
            preference.usable_for_questions = False
            update_fields.extend(("enabled", "usable_for_questions"))
    if update_fields:
        preference.save(update_fields=[*update_fields, "updated_at"])
    return preference
