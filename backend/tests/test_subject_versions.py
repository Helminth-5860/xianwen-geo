from unittest.mock import patch

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.subjects.models import (
    Subject,
    SubjectEvent,
    SubjectFieldDefinition,
    SubjectFieldOption,
    SubjectName,
    SubjectProduct,
    SubjectType,
    SubjectTypeFieldConfig,
    SubjectVersion,
)
from apps.users.models import User

PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.fixture(autouse=True)
def seed_subject_catalog():
    call_command("sync_subject_catalog", "--apply", verbosity=0)


def make_user(*, phone="13800138000", approval_status=User.ApprovalStatus.PENDING):
    return User.objects.create_user(
        phone=phone,
        nickname="Version user",
        password=PASSWORD,
        approval_status=approval_status,
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def payload(response):
    return response.json()["data"]


def add_semantic_field(
    subject_type,
    *,
    field_key,
    role,
    required=False,
    field_type=SubjectFieldDefinition.FieldType.TEXT,
    options=(),
):
    definition = SubjectFieldDefinition.objects.create(
        owner_subject_type=subject_type,
        field_key=field_key,
        field_type=field_type,
        scope=SubjectFieldDefinition.Scope.CUSTOM,
    )
    config = SubjectTypeFieldConfig.objects.create(
        subject_type=subject_type,
        field_definition=definition,
        label=field_key.replace("_", " ").title(),
        required=required,
        enabled=True,
        name_role=role,
        sort_order=100,
    )
    SubjectFieldOption.objects.bulk_create(
        [
            SubjectFieldOption(
                field_config=config,
                option_key=option_key,
                label=label,
                sort_order=index,
            )
            for index, (option_key, label) in enumerate(options)
        ]
    )
    subject_type.schema_version += 1
    subject_type.save(update_fields=["schema_version", "updated_at"])

    return config


def create_subject(client, subject_type, values):
    response = client.post(
        "/api/v1/subjects",
        {
            "subject_type_id": str(subject_type.pk),
            "expected_schema_version": subject_type.schema_version,
            "initial_values": values,
        },
        format="json",
    )
    assert response.status_code == 201
    return payload(response)


def confirmations(detail, *, unique=False, mention=False):
    return [
        {
            "candidate_key": item["candidate_key"],
            "uniqueness_confirmed": unique,
            "include_in_mention": mention,
        }
        for item in detail["product_candidates"]
    ]


@pytest.mark.django_db
def test_first_commit_uses_locked_draft_and_creates_version_one_with_semantics():
    user = make_user()
    client = client_for(user)
    subject_type = SubjectType.objects.get(key="enterprise")
    add_semantic_field(
        subject_type,
        field_key="alias_name",
        role=SubjectTypeFieldConfig.NameRole.ALIAS,
    )
    add_semantic_field(
        subject_type,
        field_key="product_name",
        role=SubjectTypeFieldConfig.NameRole.PRODUCT,
    )
    detail = create_subject(
        client,
        subject_type,
        {
            "name": "  Example\u3000Enterprise  ",
            "alias_name": " Example Alias ",
            "product_name": " Product One ",
        },
    )

    response = client.post(
        f"/api/v1/subjects/{detail['id']}/commit",
        {
            "expected_version": detail["version"],
            "products": confirmations(detail, unique=True, mention=True),
        },
        format="json",
    )
    assert response.status_code == 201
    result = payload(response)
    version = SubjectVersion.objects.get(subject_id=detail["id"])
    subject = Subject.objects.get(pk=detail["id"])
    assert version.version_no == 1
    assert version.field_values == subject.draft_values
    assert version.official_name == "Example Enterprise"
    assert subject.current_version == version
    assert subject.retest_required is False
    assert set(version.names.values_list("role", flat=True)) == {"official_name", "alias"}
    product = version.products.get()
    assert product.display_value == "Product One"
    assert product.uniqueness_confirmed is True
    assert product.include_in_mention is True
    assert result["subject"]["current_version_no"] == 1
    assert result["subject"]["has_uncommitted_changes"] is False
    assert "schema_digest" not in result["version"]
    assert "semantic_digest" not in result["version"]


@pytest.mark.django_db
def test_commit_request_is_strict_and_product_candidates_cannot_be_forged():
    user = make_user()
    client = client_for(user)
    subject_type = SubjectType.objects.get(key="enterprise")
    detail = create_subject(client, subject_type, {"name": "Strict subject"})
    endpoint = f"/api/v1/subjects/{detail['id']}/commit"

    forbidden_fields = {
        "field_values": {"name": "forged"},
        "schema_snapshot": {},
        "schema_digest": "f" * 64,
        "field_values_digest": "f" * 64,
        "semantic_digest": "f" * 64,
        "version_no": 99,
        "current_version": "f" * 32,
        "official_name": "forged",
    }
    for field, value in forbidden_fields.items():
        forbidden = client.post(
            endpoint,
            {"expected_version": detail["version"], "products": [], field: value},
            format="json",
        )
        assert forbidden.status_code == 422
        assert forbidden.json()["error"]["code"] == "VALIDATION_ERROR"

    forged = client.post(
        endpoint,
        {
            "expected_version": detail["version"],
            "products": [
                {
                    "candidate_key": "f" * 64,
                    "uniqueness_confirmed": True,
                    "include_in_mention": True,
                }
            ],
        },
        format="json",
    )
    assert forged.status_code == 422
    assert forged.json()["error"]["code"] == "SUBJECT_PRODUCT_CONFIRMATION_INVALID"
    assert not SubjectVersion.objects.exists()


@pytest.mark.django_db
def test_product_confirmation_set_rejects_missing_duplicate_extra_and_client_values():
    user = make_user()
    client = client_for(user)
    subject_type = SubjectType.objects.get(key="enterprise")
    add_semantic_field(
        subject_type,
        field_key="product_name",
        role=SubjectTypeFieldConfig.NameRole.PRODUCT,
    )
    detail = create_subject(
        client,
        subject_type,
        {"name": "Confirmation subject", "product_name": "Frozen product"},
    )
    endpoint = f"/api/v1/subjects/{detail['id']}/commit"
    valid = confirmations(detail)[0]
    invalid_sets = [
        [],
        [valid, valid],
        [valid, {**valid, "candidate_key": "f" * 64}],
    ]
    for products in invalid_sets:
        response = client.post(
            endpoint,
            {"expected_version": detail["version"], "products": products},
            format="json",
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "SUBJECT_PRODUCT_CONFIRMATION_INVALID"

    client_value = client.post(
        endpoint,
        {
            "expected_version": detail["version"],
            "products": [{**valid, "display_value": "client-forged"}],
        },
        format="json",
    )
    assert client_value.status_code == 422
    assert client_value.json()["error"]["code"] == "VALIDATION_ERROR"

    mention_without_uniqueness = client.post(
        endpoint,
        {
            "expected_version": detail["version"],
            "products": [{**valid, "uniqueness_confirmed": False, "include_in_mention": True}],
        },
        format="json",
    )
    assert mention_without_uniqueness.status_code == 422
    assert (
        mention_without_uniqueness.json()["error"]["code"] == "SUBJECT_PRODUCT_CONFIRMATION_INVALID"
    )
    assert not SubjectVersion.objects.exists()


@pytest.mark.django_db
def test_all_name_roles_use_frozen_choice_labels_and_nfkc_casefold_normalization():
    user = make_user()
    client = client_for(user)
    subject_type = SubjectType.objects.get(key="enterprise")
    alias_config = add_semantic_field(
        subject_type,
        field_key="alias_choice",
        role=SubjectTypeFieldConfig.NameRole.ALIAS,
        field_type=SubjectFieldDefinition.FieldType.SELECT,
        options=(("alias_one", "  Alias\u3000One  "),),
    )
    english_config = add_semantic_field(
        subject_type,
        field_key="english_choices",
        role=SubjectTypeFieldConfig.NameRole.ENGLISH_NAME,
        field_type=SubjectFieldDefinition.FieldType.MULTI,
        options=(("english_one", "  Example  EN  "),),
    )
    product_config = add_semantic_field(
        subject_type,
        field_key="product_choice",
        role=SubjectTypeFieldConfig.NameRole.PRODUCT,
        field_type=SubjectFieldDefinition.FieldType.SINGLE,
        options=(("product_one", "  Product\u3000One  "),),
    )
    detail = create_subject(
        client,
        subject_type,
        {
            "name": "  ＡＣＭＥ　Corp  ",
            "alias_choice": "alias_one",
            "english_choices": ["english_one"],
            "product_choice": "product_one",
        },
    )

    for config in (alias_config, english_config, product_config):
        option = config.options.get()
        option.label = "Changed current label"
        option.version += 1
        option.save(update_fields=["label", "version", "updated_at"])

    committed = client.post(
        f"/api/v1/subjects/{detail['id']}/commit",
        {
            "expected_version": detail["version"],
            "products": confirmations(detail, unique=True),
        },
        format="json",
    )
    assert committed.status_code == 201
    version = SubjectVersion.objects.get(subject_id=detail["id"])
    names = {(item.role, item.display_value, item.matching_value) for item in version.names.all()}
    assert names == {
        (SubjectName.Role.OFFICIAL_NAME, "ACME Corp", "acme corp"),
        (SubjectName.Role.ALIAS, "Alias One", "alias one"),
        (SubjectName.Role.ENGLISH_NAME, "Example EN", "example en"),
    }
    product = version.products.get()
    assert product.display_value == "Product One"
    assert product.matching_value == "product one"

    patched_response = client.patch(
        f"/api/v1/subjects/{detail['id']}/draft",
        {
            "expected_version": payload(committed)["subject"]["version"],
            "values": {"name": "Bad\u0001Name"},
        },
        format="json",
    )
    assert patched_response.status_code == 200
    patched = payload(patched_response)
    rejected = client.post(
        f"/api/v1/subjects/{detail['id']}/commit",
        {
            "expected_version": patched["version"],
            "products": confirmations(patched, unique=True),
        },
        format="json",
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "SUBJECT_SEMANTICS_INVALID"


@pytest.mark.django_db
def test_required_fields_archived_state_and_account_approval_boundaries():
    user = make_user(approval_status=User.ApprovalStatus.REJECTED)
    client = client_for(user)
    subject_type = SubjectType.objects.get(key="enterprise")
    incomplete = create_subject(client, subject_type, {})
    rejected = client.post(
        f"/api/v1/subjects/{incomplete['id']}/commit",
        {"expected_version": incomplete["version"], "products": []},
        format="json",
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "SUBJECT_REQUIRED_FIELDS_INCOMPLETE"
    assert "name" in rejected.json()["error"]["details"]["fields"]

    updated = client.patch(
        f"/api/v1/subjects/{incomplete['id']}/draft",
        {
            "expected_version": incomplete["version"],
            "values": {"name": "Rejected account subject"},
        },
        format="json",
    )
    valid = payload(updated)
    committed = client.post(
        f"/api/v1/subjects/{valid['id']}/commit",
        {"expected_version": valid["version"], "products": []},
        format="json",
    )
    assert committed.status_code == 201
    assert SubjectVersion.objects.get(subject_id=valid["id"]).version_no == 1

    subject = Subject.objects.get(pk=valid["id"])
    archived = client.post(
        f"/api/v1/subjects/{subject.pk}/archive",
        {"expected_version": subject.version},
        format="json",
    )
    archived_detail = payload(archived)
    denied = client.post(
        f"/api/v1/subjects/{subject.pk}/commit",
        {"expected_version": archived_detail["version"], "products": []},
        format="json",
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "SUBJECT_STATE_CONFLICT"


@pytest.mark.django_db
def test_semantic_changes_create_contiguous_version_and_no_changes_is_409():
    user = make_user()
    client = client_for(user)
    subject_type = SubjectType.objects.get(key="enterprise")
    add_semantic_field(
        subject_type,
        field_key="product_name",
        role=SubjectTypeFieldConfig.NameRole.PRODUCT,
    )
    detail = create_subject(
        client,
        subject_type,
        {"name": "Versioned subject", "product_name": "Product"},
    )
    endpoint = f"/api/v1/subjects/{detail['id']}/commit"
    first = client.post(
        endpoint,
        {"expected_version": detail["version"], "products": confirmations(detail)},
        format="json",
    )
    first_subject = payload(first)["subject"]

    no_changes = client.post(
        endpoint,
        {
            "expected_version": first_subject["version"],
            "products": confirmations(detail),
        },
        format="json",
    )
    assert no_changes.status_code == 409
    assert no_changes.json()["error"]["code"] == "SUBJECT_VERSION_NO_CHANGES"

    second = client.post(
        endpoint,
        {
            "expected_version": first_subject["version"],
            "products": confirmations(detail, unique=True),
        },
        format="json",
    )
    assert second.status_code == 201
    subject = Subject.objects.get(pk=detail["id"])
    assert list(subject.versions.values_list("version_no", flat=True)) == [1, 2]
    assert subject.current_version.version_no == 2
    assert subject.retest_required is True
    assert subject.events.filter(event_type=SubjectEvent.EventType.VERSION_COMMITTED).count() == 2
    assert payload(second)["subject"]["has_uncommitted_changes"] is False

    patched = client.patch(
        f"/api/v1/subjects/{detail['id']}/draft",
        {
            "expected_version": payload(second)["subject"]["version"],
            "values": {"name": "Draft changed after formal version"},
        },
        format="json",
    )
    assert patched.status_code == 200
    assert payload(patched)["has_uncommitted_changes"] is True


@pytest.mark.django_db
def test_commit_allows_draft_and_active_without_subscription_and_blocks_unavailable_accounts():
    subject_type = SubjectType.objects.get(key="enterprise")
    for index, subject_status in enumerate((Subject.Status.DRAFT, Subject.Status.ACTIVE)):
        user = make_user(phone=f"138001381{index:02d}")
        client = client_for(user)
        detail = create_subject(client, subject_type, {"name": f"Status {subject_status}"})
        if subject_status == Subject.Status.ACTIVE:
            Subject.objects.filter(pk=detail["id"]).update(status=Subject.Status.ACTIVE)
        response = client.post(
            f"/api/v1/subjects/{detail['id']}/commit",
            {"expected_version": detail["version"], "products": []},
            format="json",
        )
        assert response.status_code == 201

    for index, account_status in enumerate(
        (
            User.AccountStatus.CANCEL_PENDING,
            User.AccountStatus.FROZEN,
            User.AccountStatus.CANCELLED,
        )
    ):
        user = make_user(phone=f"138001382{index:02d}")
        client = client_for(user)
        detail = create_subject(client, subject_type, {"name": f"Blocked {account_status}"})
        user.account_status = account_status
        if account_status in {User.AccountStatus.FROZEN, User.AccountStatus.CANCELLED}:
            user.is_active = False
        user.save(update_fields=["account_status", "is_active", "updated_at"])
        response = client.post(
            f"/api/v1/subjects/{detail['id']}/commit",
            {"expected_version": detail["version"], "products": []},
            format="json",
        )
        assert response.status_code == 403
        assert not SubjectVersion.objects.filter(subject_id=detail["id"]).exists()


@pytest.mark.django_db
def test_history_uses_version_frozen_schema_and_never_exposes_internal_digests():
    user = make_user()
    client = client_for(user)
    subject_type = SubjectType.objects.get(key="enterprise")
    detail = create_subject(client, subject_type, {"name": "Frozen history"})
    committed = client.post(
        f"/api/v1/subjects/{detail['id']}/commit",
        {"expected_version": detail["version"], "products": []},
        format="json",
    )
    version_id = payload(committed)["version"]["id"]
    name_config = subject_type.field_configs.get(field_definition__field_key="name")
    name_config.label = "Changed current label"
    name_config.version += 1
    name_config.save(update_fields=["label", "version", "updated_at"])

    history = client.get(f"/api/v1/subjects/{detail['id']}/versions/{version_id}")
    assert history.status_code == 200
    result = payload(history)
    frozen_name = next(
        field for field in result["form_schema"]["fields"] if field["field_key"] == "name"
    )
    assert frozen_name["label"] != "Changed current label"
    assert not {
        "schema_snapshot",
        "schema_digest",
        "field_values_digest",
        "semantic_digest",
        "matching_value",
        "created_by",
    } & set(result)


@pytest.mark.django_db
def test_commit_failure_rolls_back_version_semantics_pointer_event_and_retest():
    user = make_user()
    client = client_for(user)
    subject_type = SubjectType.objects.get(key="enterprise")
    detail = create_subject(client, subject_type, {"name": "Rollback subject"})
    with patch(
        "apps.subjects.version_services.SubjectEvent.objects.create", side_effect=RuntimeError
    ):
        response = client.post(
            f"/api/v1/subjects/{detail['id']}/commit",
            {"expected_version": detail["version"], "products": []},
            format="json",
        )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    subject = Subject.objects.get(pk=detail["id"])
    assert subject.current_version_id is None
    assert subject.retest_required is False
    assert not SubjectVersion.objects.exists()
    assert not SubjectName.objects.exists()
    assert not SubjectProduct.objects.exists()
