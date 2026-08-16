import uuid

import pytest
from django.core.management import call_command
from django.db import DatabaseError, IntegrityError, connection, transaction

from apps.questions.catalog import BUILTIN_QUESTION_CATEGORIES
from apps.questions.models import (
    QuestionCategory,
    QuestionCategorySubjectType,
    QuestionTag,
)
from apps.subjects.models import SubjectType

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="PostgreSQL question catalog guards require PostgreSQL.",
    ),
]


@pytest.fixture(autouse=True)
def seed_catalogs():
    call_command("sync_subject_catalog", "--apply", verbosity=0)
    for item in BUILTIN_QUESTION_CATEGORIES:
        QuestionCategory.objects.get_or_create(
            key=item.key,
            defaults={
                "name": item.name,
                "normalized_name": item.name.casefold(),
                "description": item.description,
                "generation_guidance": item.generation_guidance,
                "sort_order": item.sort_order,
                "is_builtin": True,
            },
        )


def test_builtin_category_identity_and_delete_are_database_protected():
    category = QuestionCategory.objects.get(key="brand_awareness")
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE question_categories SET key = %s, version = version + 1 WHERE id = %s",
                ["changed", category.pk],
            )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM question_categories WHERE id = %s", [category.pk])


def test_direct_update_requires_exact_version_increment():
    category = QuestionCategory.objects.get(key="brand_awareness")
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE question_categories SET description = %s WHERE id = %s",
                ["绕过版本", category.pk],
            )
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                (
                    "UPDATE question_categories SET description = %s, "
                    "version = version + 1 WHERE id = %s"
                ),
                ["合法版本推进", category.pk],
            )
    category.refresh_from_db()
    assert category.version == 2


def test_tag_machine_identity_is_immutable_but_custom_tag_can_be_removed():
    tag = QuestionTag.objects.create(
        key="custom_tag",
        name="自定义标签",
        normalized_name="自定义标签",
        is_builtin=False,
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE question_tags SET is_builtin = true, version = version + 1 WHERE id = %s",
                [tag.pk],
            )
    tag.delete()
    assert not QuestionTag.objects.filter(pk=tag.pk).exists()


def test_applicability_link_is_unique_and_subject_type_is_protected():
    category = QuestionCategory.objects.get(key="brand_awareness")
    subject_type = SubjectType.objects.get(key="enterprise")
    QuestionCategorySubjectType.objects.create(category=category, subject_type=subject_type)
    with pytest.raises(IntegrityError), transaction.atomic():
        QuestionCategorySubjectType.objects.create(category=category, subject_type=subject_type)
    with pytest.raises(DatabaseError), transaction.atomic():
        subject_type.delete()


def test_normalized_names_are_unique_at_database_boundary():
    suffix = uuid.uuid4().hex[:8]
    QuestionTag.objects.create(
        key=f"first_{suffix}", name="唯一标签", normalized_name=f"unique-{suffix}"
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        QuestionTag.objects.create(
            key=f"second_{suffix}", name="另一个标签", normalized_name=f"unique-{suffix}"
        )
