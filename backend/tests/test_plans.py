import uuid
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.urls import resolve
from rest_framework.test import APIClient

from apps.admin_rbac.catalog import CATALOG_BY_KEY
from apps.admin_rbac.models import AuditEvent, RiskAction, RiskPolicy
from apps.admin_rbac.risk_catalog import RISK_ACTION_BY_KEY
from apps.admin_rbac.risk_handlers import HANDLER_REGISTRY, HANDLER_SPECS
from apps.plans.catalog import MODEL_KEYS, load_limit_catalog
from apps.plans.models import PlanLimitDefinition
from apps.plans.services import (
    PlanDraftAlreadyExists,
    PlanImmutable,
    PlanLimitInvalid,
    PlanPublishValidationFailed,
    PlanStateConflict,
    PlanVersionConflict,
    archive_plan,
    build_effective_config,
    copy_plan,
    create_plan,
    create_plan_version,
    normalize_display_price,
    publish_plan_version,
    retire_plan_version,
    set_plan_offline,
    set_plan_online,
    update_plan_version,
    validate_publishable,
)
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client


def actor(phone="13900139000"):
    user = User(phone=phone, nickname="套餐管理员", is_staff=True, is_superuser=True)
    user.account_status = User.AccountStatus.ACTIVE
    user.set_unusable_password()
    user.synchronize_active_state()
    user.full_clean(exclude={"password"})
    user.save()
    assert not user.has_usable_password()
    return user


def make_plan(user, code="standard", mode="fixed"):
    return create_plan(
        plan_id=uuid.uuid4(),
        actor=user,
        data={
            "code": code,
            "name": "标准套餐",
            "description": "展示说明",
            "price_display_mode": mode,
            "display_price": "99.00" if mode == "fixed" else None,
            "is_trial": False,
            "sort_order": 10,
        },
    )


def make_draft(user, plan):
    return create_plan_version(plan_id=plan.pk, actor=user, expected_plan_version=plan.version)


def publish(user, version, confirm=True):
    return publish_plan_version(
        version_id=version.pk,
        actor=user,
        expected_version=version.version,
        confirm_informal_composite=confirm,
    )


def value_of(item):
    if item.value_type == "integer":
        return item.integer_value
    if item.value_type == "boolean":
        return item.boolean_value
    if item.value_type in {"text", "enum"}:
        return item.text_value
    return None if item.json_value == {"value": None} else item.json_value


@pytest.mark.django_db
def test_plan_code_price_modes_decimal_cny_and_no_float():
    user = actor()
    plan = make_plan(user, "  Standard_2026  ")
    assert plan.code == "standard_2026" and plan.display_price == Decimal("99.00")
    assert plan.display_currency == "CNY"
    assert make_plan(user, "contact", "contact").display_price is None
    for invalid in (1.25, True, "NaN", "Infinity"):
        with pytest.raises(PlanLimitInvalid):
            normalize_display_price("fixed", invalid)


@pytest.mark.django_db
def test_catalog_compatibility_storage_and_sync_idempotence():
    definitions = {item.key: item for item in load_limit_catalog()[1]}
    assert {
        "subject_active_limit",
        "concurrent_detection_jobs",
        "article_credits",
        "image_credits",
        "allow_user_model_selection",
    } <= definitions.keys()
    assert "subject_count" not in definitions
    assert definitions["valid_days"].storage_kind == "plan_version_field"
    assert definitions["allowed_model_keys"].storage_kind == "model_permissions"
    assert definitions["allowed_model_keys"].status == "inactive"
    call_command("sync_plan_catalog")
    call_command("sync_plan_catalog")
    assert PlanLimitDefinition.objects.count() == len(definitions)


@pytest.mark.django_db
def test_single_draft_version_number_and_optimistic_lock():
    user, plan = actor(), None
    plan = make_plan(user)
    draft = make_draft(user, plan)
    plan.refresh_from_db()
    assert draft.version_no == 1
    with pytest.raises(PlanDraftAlreadyExists):
        make_draft(user, plan)
    with pytest.raises(PlanVersionConflict):
        update_plan_version(
            version_id=draft.pk,
            actor=user,
            expected_version=99,
            valid_days=30,
            queue_priority=100,
            limits=[],
            model_permissions=[],
        )


@pytest.mark.django_db
def test_publish_snapshot_digest_pointer_and_immutability():
    user, plan = actor(), None
    plan = make_plan(user)
    published = publish(user, make_draft(user, plan))
    plan.refresh_from_db()
    snapshot, digest = build_effective_config(published, published.snapshot_generated_at)
    assert plan.status == "published" and plan.current_published_version_id == published.pk
    assert snapshot == published.effective_config and digest == published.config_digest
    assert len(digest) == 64 and list(snapshot["limits"]) == sorted(snapshot["limits"])
    with pytest.raises(PlanImmutable):
        update_plan_version(
            version_id=published.pk,
            actor=user,
            expected_version=published.version,
            valid_days=60,
            queue_priority=100,
            limits=[],
            model_permissions=[],
        )


@pytest.mark.django_db
def test_offline_publish_retire_archive_and_pointer_state_machine():
    user, plan = actor(), None
    plan = make_plan(user)
    first = publish(user, make_draft(user, plan))
    plan.refresh_from_db()
    with pytest.raises(PlanStateConflict):
        archive_plan(plan_id=plan.pk, actor=user, expected_version=plan.version)
    plan = set_plan_offline(plan_id=plan.pk, actor=user, expected_version=plan.version)
    second = publish(user, make_draft(user, plan))
    plan.refresh_from_db()
    first.refresh_from_db()
    assert plan.status == "offline" and first.status == "retired"
    plan = set_plan_online(plan_id=plan.pk, actor=user, expected_version=plan.version)
    plan = set_plan_offline(plan_id=plan.pk, actor=user, expected_version=plan.version)
    second.refresh_from_db()
    retire_plan_version(version_id=second.pk, actor=user, expected_version=second.version)
    plan.refresh_from_db()
    archived = archive_plan(plan_id=plan.pk, actor=user, expected_version=plan.version)
    assert archived.status == "archived" and archived.current_published_version_id is None


@pytest.mark.django_db
def test_copy_deep_and_informal_composite_confirmation():
    user, source_plan = actor(), None
    source_plan = make_plan(user)
    source = publish(user, make_draft(user, source_plan))
    source_plan.refresh_from_db()
    new_plan, draft = copy_plan(
        source_plan_id=source_plan.pk,
        new_plan_id=uuid.uuid4(),
        actor=user,
        expected_source_plan_version=source_plan.version,
        new_code="standard-copy",
        new_name="副本",
        source_version_id=source.pk,
    )
    assert new_plan.status == "draft" and new_plan.current_published_version_id is None
    assert draft.limits.count() == source.limits.count()
    assert not set(draft.limits.values_list("id", flat=True)) & set(
        source.limits.values_list("id", flat=True)
    )
    limits = [{"key": item.limit_key, "value": value_of(item)} for item in draft.limits.all()]
    next(item for item in limits if item["key"] == "max_models_per_detection")["value"] = 3
    models = [
        {"model_key": key, "sort_order": i, "selected_by_default": True}
        for i, key in enumerate(MODEL_KEYS[:3])
    ]
    draft = update_plan_version(
        version_id=draft.pk,
        actor=user,
        expected_version=draft.version,
        valid_days=30,
        queue_priority=100,
        limits=limits,
        model_permissions=models,
    )
    with pytest.raises(PlanPublishValidationFailed):
        publish(user, draft, False)
    published = publish(user, draft, True)
    assert (
        validate_publishable(published, confirm_informal_composite=True)[
            "supports_formal_composite"
        ]
        is False
    )


@pytest.mark.django_db
def test_permissions_risk_handlers_and_frozen_defaults_complete():
    actions = {
        "plan.create",
        "plan.update",
        "plan.copy",
        "plan.online",
        "plan.offline",
        "plan.archive",
        "plan.version.create",
        "plan.version.update",
        "plan.version.publish",
        "plan.version.retire",
    }
    assert {
        "menu.admin.plans",
        "plans.create",
        "plans.archive",
        "plan_versions.publish",
        "plan_limits.update",
    } <= set(CATALOG_BY_KEY)
    assert actions <= set(RISK_ACTION_BY_KEY) <= set(HANDLER_SPECS)
    assert actions <= set(HANDLER_REGISTRY)
    assert RiskAction.objects.filter(pk__in=actions).count() == 10
    assert RiskPolicy.objects.filter(action_id__in=actions).count() == 10
    assert RISK_ACTION_BY_KEY["plan.version.publish"].default_mode == "password"
    assert RISK_ACTION_BY_KEY["plan.archive"].default_mode == "two_person"


@pytest.mark.django_db
def test_public_api_only_published_and_admin_post_same_path_csrf_audit():
    user, draft_plan, visible = actor(), None, None
    draft_plan = make_plan(user, "draft")
    visible = make_plan(user, "visible")
    publish(user, make_draft(user, visible))
    visible.refresh_from_db()
    public = APIClient()
    items = public.get("/api/v1/plans").json()["data"]
    assert [item["id"] for item in items] == [str(visible.pk)]
    assert {"effective_config", "config_digest", "handler"}.isdisjoint(items[0])
    assert public.get(f"/api/v1/plans/{draft_plan.pk}").status_code == 404
    client = authenticate_admin_client(APIClient(), user)
    payload = {
        "code": "api-plan",
        "name": "API 套餐",
        "price_display_mode": "fixed",
        "display_price": "18.80",
        "confirmed": True,
    }
    assert client.post("/api/v1/admin/plans", payload, format="json").status_code == 200
    assert AuditEvent.objects.filter(action_key="plan.create", outcome="executed").exists()
    blocked = authenticate_admin_client(APIClient(enforce_csrf_checks=True), user).post(
        "/api/v1/admin/plans", payload | {"code": "blocked"}, format="json"
    )
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "CSRF_FAILED"


@pytest.mark.django_db
def test_frozen_routes_exist_without_legacy_create():
    plan_id, version_id = uuid.uuid4(), uuid.uuid4()
    routes = {
        "/api/v1/admin/plans": "admin-plan-list",
        f"/api/v1/admin/plans/{plan_id}": "admin-plan-detail",
        f"/api/v1/admin/plans/{plan_id}/versions": "admin-plan-version-list",
        f"/api/v1/admin/plan-versions/{version_id}": "admin-plan-version-detail",
        "/api/v1/admin/plan-limit-definitions": "admin-plan-limit-definitions",
        "/api/v1/plans": "public-plan-list",
        f"/api/v1/plans/{plan_id}": "public-plan-detail",
    }
    for path, name in routes.items():
        assert resolve(path).url_name == name
    assert APIClient().post("/api/v1/admin/plans/create", {}, format="json").status_code == 404
