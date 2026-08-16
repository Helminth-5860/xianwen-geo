from django.db import IntegrityError, transaction

from apps.admin_rbac.audit_services import record_audit_event
from apps.subjects.models import SubjectType

from .exceptions import (
    QuestionCatalogDuplicate,
    QuestionCatalogStateConflict,
    QuestionCatalogValuesInvalid,
    QuestionCatalogVersionConflict,
)
from .models import (
    QuestionCategory,
    QuestionCategorySubjectType,
    QuestionTag,
    QuestionTagSubjectType,
)
from .normalization import (
    QuestionCatalogNormalizationError,
    normalize_catalog_key,
    normalize_catalog_text,
)


def _text(value, *, maximum, required):
    try:
        return normalize_catalog_text(value, maximum=maximum, required=required)
    except QuestionCatalogNormalizationError as exc:
        raise QuestionCatalogValuesInvalid from exc


def _key(value):
    try:
        return normalize_catalog_key(value)
    except QuestionCatalogNormalizationError as exc:
        raise QuestionCatalogValuesInvalid from exc


def _subject_types(subject_type_ids):
    unique_ids = set(subject_type_ids)
    if len(unique_ids) != len(subject_type_ids):
        raise QuestionCatalogValuesInvalid
    rows = list(SubjectType.objects.filter(pk__in=unique_ids).order_by("pk"))
    if len(rows) != len(unique_ids):
        raise QuestionCatalogValuesInvalid
    return rows


def _audit(request, *, action, target_type, target_id, before=None, after=None):
    return record_audit_event(
        request=request,
        category="question_catalog",
        action_key=action,
        outcome="executed",
        actor=request.user,
        target_type=target_type,
        target_id=target_id,
        safe_before=before or {},
        safe_after=after or {},
    )


def _summary(row):
    return {"key": row.key, "status": row.status, "version": row.version}


def _category_subject_ids(category):
    return list(category.applicable_subject_types.order_by("id").values_list("id", flat=True))


def _tag_subject_ids(tag):
    return list(tag.applicable_subject_types.order_by("id").values_list("id", flat=True))


def _category_values(data):
    name, normalized_name = _text(data["name"], maximum=150, required=True)
    description, _ = _text(data.get("description", ""), maximum=500, required=False)
    guidance, _ = _text(data.get("generation_guidance", ""), maximum=2000, required=False)
    return name, normalized_name, description, guidance


@transaction.atomic
def create_question_category(*, request, data):
    subject_types = _subject_types(data.pop("applicable_subject_type_ids", []))
    name, normalized_name, description, guidance = _category_values(data)
    try:
        category = QuestionCategory.objects.create(
            key=_key(data["key"]),
            name=name,
            normalized_name=normalized_name,
            description=description,
            generation_guidance=guidance,
            sort_order=data.get("sort_order", 0),
            created_by=request.user,
            updated_by=request.user,
        )
        QuestionCategorySubjectType.objects.bulk_create(
            [
                QuestionCategorySubjectType(category=category, subject_type=subject_type)
                for subject_type in subject_types
            ]
        )
    except IntegrityError as exc:
        raise QuestionCatalogDuplicate from exc
    _audit(
        request,
        action="question_category.create",
        target_type="question_category",
        target_id=category.pk,
        after={**_summary(category), "subject_type_ids": [str(row.pk) for row in subject_types]},
    )
    return category


@transaction.atomic
def update_question_category(*, request, category_id, data):
    category = QuestionCategory.objects.select_for_update().get(pk=category_id)
    if category.version != data.pop("expected_version"):
        raise QuestionCatalogVersionConflict
    before = {
        **_summary(category),
        "subject_type_ids": [str(pk) for pk in _category_subject_ids(category)],
    }
    if "name" in data:
        category.name, category.normalized_name = _text(data["name"], maximum=150, required=True)
    if "description" in data:
        category.description, _ = _text(data["description"], maximum=500, required=False)
    if "generation_guidance" in data:
        category.generation_guidance, _ = _text(
            data["generation_guidance"], maximum=2000, required=False
        )
    if "sort_order" in data:
        category.sort_order = data["sort_order"]
    subject_type_ids = data.get("applicable_subject_type_ids")
    try:
        if subject_type_ids is not None:
            subject_types = _subject_types(subject_type_ids)
            category.subject_type_links.all().delete()
            QuestionCategorySubjectType.objects.bulk_create(
                [
                    QuestionCategorySubjectType(category=category, subject_type=subject_type)
                    for subject_type in subject_types
                ]
            )
        category.version += 1
        category.updated_by = request.user
        category.save()
    except IntegrityError as exc:
        raise QuestionCatalogDuplicate from exc
    _audit(
        request,
        action="question_category.update",
        target_type="question_category",
        target_id=category.pk,
        before=before,
        after={
            **_summary(category),
            "subject_type_ids": [str(pk) for pk in _category_subject_ids(category)],
        },
    )
    return category


@transaction.atomic
def set_question_category_status(*, request, category_id, status, expected_version):
    category = QuestionCategory.objects.select_for_update().get(pk=category_id)
    if category.version != expected_version:
        raise QuestionCatalogVersionConflict
    if category.status == status:
        raise QuestionCatalogStateConflict
    before = _summary(category)
    category.status = status
    category.version += 1
    category.updated_by = request.user
    category.save()
    _audit(
        request,
        action=f"question_category.{status}",
        target_type="question_category",
        target_id=category.pk,
        before=before,
        after=_summary(category),
    )
    return category


def _tag_values(data):
    name, normalized_name = _text(data["name"], maximum=150, required=True)
    description, _ = _text(data.get("description", ""), maximum=500, required=False)
    return name, normalized_name, description


@transaction.atomic
def create_question_tag(*, request, data):
    subject_types = _subject_types(data.pop("applicable_subject_type_ids", []))
    name, normalized_name, description = _tag_values(data)
    try:
        tag = QuestionTag.objects.create(
            key=_key(data["key"]),
            name=name,
            normalized_name=normalized_name,
            description=description,
            sort_order=data.get("sort_order", 0),
            created_by=request.user,
            updated_by=request.user,
        )
        QuestionTagSubjectType.objects.bulk_create(
            [QuestionTagSubjectType(tag=tag, subject_type=row) for row in subject_types]
        )
    except IntegrityError as exc:
        raise QuestionCatalogDuplicate from exc
    _audit(
        request,
        action="question_tag.create",
        target_type="question_tag",
        target_id=tag.pk,
        after={**_summary(tag), "subject_type_ids": [str(row.pk) for row in subject_types]},
    )
    return tag


@transaction.atomic
def update_question_tag(*, request, tag_id, data):
    tag = QuestionTag.objects.select_for_update().get(pk=tag_id)
    if tag.version != data.pop("expected_version"):
        raise QuestionCatalogVersionConflict
    before = {**_summary(tag), "subject_type_ids": [str(pk) for pk in _tag_subject_ids(tag)]}
    if "name" in data:
        tag.name, tag.normalized_name = _text(data["name"], maximum=150, required=True)
    if "description" in data:
        tag.description, _ = _text(data["description"], maximum=500, required=False)
    if "sort_order" in data:
        tag.sort_order = data["sort_order"]
    subject_type_ids = data.get("applicable_subject_type_ids")
    try:
        if subject_type_ids is not None:
            subject_types = _subject_types(subject_type_ids)
            tag.subject_type_links.all().delete()
            QuestionTagSubjectType.objects.bulk_create(
                [QuestionTagSubjectType(tag=tag, subject_type=row) for row in subject_types]
            )
        tag.version += 1
        tag.updated_by = request.user
        tag.save()
    except IntegrityError as exc:
        raise QuestionCatalogDuplicate from exc
    _audit(
        request,
        action="question_tag.update",
        target_type="question_tag",
        target_id=tag.pk,
        before=before,
        after={**_summary(tag), "subject_type_ids": [str(pk) for pk in _tag_subject_ids(tag)]},
    )
    return tag


@transaction.atomic
def set_question_tag_status(*, request, tag_id, status, expected_version):
    tag = QuestionTag.objects.select_for_update().get(pk=tag_id)
    if tag.version != expected_version:
        raise QuestionCatalogVersionConflict
    if tag.status == status:
        raise QuestionCatalogStateConflict
    before = _summary(tag)
    tag.status = status
    tag.version += 1
    tag.updated_by = request.user
    tag.save()
    _audit(
        request,
        action=f"question_tag.{status}",
        target_type="question_tag",
        target_id=tag.pk,
        before=before,
        after=_summary(tag),
    )
    return tag
