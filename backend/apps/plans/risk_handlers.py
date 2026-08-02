from rest_framework.exceptions import NotFound

from apps.admin_rbac.permissions import AdminContext, resolve_admin_context
from apps.admin_rbac.risk_handlers import HandlerContext, HandlerResult, HandlerSpec
from apps.admin_rbac.scopes import scoped_customer_or_404
from apps.users.models import User

from .application_services import (
    admin_change_application,
    scoped_application_or_404,
)
from .models import Plan, PlanVersion
from .serializers import (
    EmptyPlanPayloadSerializer,
    PlanCopyPayloadSerializer,
    PlanCreatePayloadSerializer,
    PlanPublishPayloadSerializer,
    PlanUpdatePayloadSerializer,
    PlanVersionCreatePayloadSerializer,
    PlanVersionUpdatePayloadSerializer,
)
from .services import (
    archive_plan,
    copy_plan,
    create_plan,
    create_plan_version,
    publish_plan_version,
    retire_plan_version,
    set_plan_offline,
    set_plan_online,
    update_plan,
    update_plan_version,
    validate_publishable,
)
from .subscription_serializers import (
    GrantTrialPayloadSerializer,
    OpenSubscriptionPayloadSerializer,
    TerminateSubscriptionPayloadSerializer,
)
from .subscription_services import (
    activate_application,
    grant_trial,
    scoped_subscription_or_404,
    terminate_subscription,
)


def _plan_version(user, context: AdminContext, target_id, lock):
    query = Plan.objects.all()
    if lock:
        query = query.select_for_update()
    try:
        return query.only("version").get(pk=target_id).version
    except Plan.DoesNotExist as exc:
        raise NotFound from exc


def _new_plan_version(user, context: AdminContext, target_id, lock):
    query = Plan.objects.all()
    if lock:
        query = query.select_for_update()
    plan = query.only("version").filter(pk=target_id).first()
    return plan.version if plan else 0


def _plan_version_record_version(user, context: AdminContext, target_id, lock):
    query = PlanVersion.objects.all()
    if lock:
        query = query.select_for_update()
    try:
        return query.only("version").get(pk=target_id).version
    except PlanVersion.DoesNotExist as exc:
        raise NotFound from exc


def _plan_result(plan):
    return {
        "id": str(plan.pk),
        "code": plan.code,
        "name": plan.name,
        "status": plan.status,
        "version": plan.version,
        "current_published_version_id": (
            str(plan.current_published_version_id) if plan.current_published_version_id else None
        ),
    }


def _version_result(version):
    return {
        "id": str(version.pk),
        "plan_id": str(version.plan_id),
        "version_no": version.version_no,
        "status": version.status,
        "version": version.version,
    }


def handle_plan_create(context: HandlerContext) -> HandlerResult:
    plan = create_plan(
        plan_id=context.target_id,
        actor=context.requester,
        data=context.payload,
    )
    result = _plan_result(plan)
    return HandlerResult({}, result, result)


def handle_plan_update(context: HandlerContext) -> HandlerResult:
    before = _plan_result(Plan.objects.get(pk=context.target_id))
    plan = update_plan(
        plan_id=context.target_id,
        actor=context.requester,
        expected_version=context.target_version,
        data=context.payload,
    )
    after = _plan_result(plan)
    return HandlerResult(before, after, after)


def handle_plan_copy(context: HandlerContext) -> HandlerResult:
    plan, version = copy_plan(
        source_plan_id=context.target_id,
        new_plan_id=context.payload["new_plan_id"],
        actor=context.requester,
        expected_source_plan_version=context.target_version,
        new_code=context.payload["new_code"],
        new_name=context.payload["new_name"],
        source_version_id=context.payload.get("source_version_id"),
    )
    result = {**_plan_result(plan), "draft_version": _version_result(version)}
    return HandlerResult({}, {"copied": True, "new_plan_id": str(plan.pk)}, result)


def handle_plan_version_create(context: HandlerContext) -> HandlerResult:
    version = create_plan_version(
        plan_id=context.target_id,
        actor=context.requester,
        expected_plan_version=context.target_version,
        source_version_id=context.payload.get("source_version_id"),
    )
    result = _version_result(version)
    return HandlerResult({}, result, result)


def handle_plan_version_update(context: HandlerContext) -> HandlerResult:
    before = _version_result(PlanVersion.objects.get(pk=context.target_id))
    version = update_plan_version(
        version_id=context.target_id,
        actor=context.requester,
        expected_version=context.target_version,
        valid_days=context.payload["valid_days"],
        queue_priority=context.payload["queue_priority"],
        limits=context.payload["limits"],
        model_permissions=context.payload["model_permissions"],
    )
    after = _version_result(version)
    return HandlerResult(before, after, after)


def handle_plan_version_publish(context: HandlerContext) -> HandlerResult:
    before = _version_result(PlanVersion.objects.get(pk=context.target_id))
    version = publish_plan_version(
        version_id=context.target_id,
        actor=context.requester,
        expected_version=context.target_version,
        confirm_informal_composite=context.payload.get("confirm_informal_composite", False),
    )
    after = _version_result(version)
    capability = validate_publishable(version, confirm_informal_composite=True)
    safe_after = {
        **after,
        "supports_formal_composite": capability["supports_formal_composite"],
        "informal_confirmation": context.payload.get("confirm_informal_composite", False),
    }
    return HandlerResult(before, safe_after, after)


def handle_plan_online(context: HandlerContext) -> HandlerResult:
    before = _plan_result(Plan.objects.get(pk=context.target_id))
    plan = set_plan_online(
        plan_id=context.target_id,
        actor=context.requester,
        expected_version=context.target_version,
    )
    after = _plan_result(plan)
    return HandlerResult(before, after, after)


def handle_plan_offline(context: HandlerContext) -> HandlerResult:
    before = _plan_result(Plan.objects.get(pk=context.target_id))
    plan = set_plan_offline(
        plan_id=context.target_id,
        actor=context.requester,
        expected_version=context.target_version,
    )
    after = _plan_result(plan)
    return HandlerResult(before, after, after)


def handle_plan_archive(context: HandlerContext) -> HandlerResult:
    before = _plan_result(Plan.objects.get(pk=context.target_id))
    plan = archive_plan(
        plan_id=context.target_id,
        actor=context.requester,
        expected_version=context.target_version,
    )
    after = _plan_result(plan)
    return HandlerResult(before, after, after)


def handle_plan_version_retire(context: HandlerContext) -> HandlerResult:
    before = _version_result(PlanVersion.objects.get(pk=context.target_id))
    version = retire_plan_version(
        version_id=context.target_id,
        actor=context.requester,
        expected_version=context.target_version,
    )
    after = _version_result(version)
    return HandlerResult(before, after, after)


def _application_version(user, context: AdminContext, target_id, lock):
    application = scoped_application_or_404(user, context, target_id, lock=lock)
    return application.version


def _handle_application(context, action):
    admin_context = context.request.admin_context
    application = scoped_application_or_404(context.requester, admin_context, context.target_id)
    before = {"status": application.status, "version": application.version}
    application = admin_change_application(
        requester=context.requester,
        admin_context=admin_context,
        application_id=context.target_id,
        expected_version=context.target_version,
        action=action,
        request_id=context.request.request_id,
    )
    after = {"status": application.status, "version": application.version}
    return HandlerResult(
        before,
        after,
        {"application_id": str(application.pk), **after},
        application.applicant,
    )


def handle_plan_application_contact(context):
    return _handle_application(context, "contact")


def handle_plan_application_close(context):
    return _handle_application(context, "close")


def _subscription_context(user):
    context = resolve_admin_context(user)
    if context is None:
        raise NotFound
    return context


def _customer_status_version(user, context: AdminContext, target_id, lock):
    scoped_customer_or_404(user, context, target_id)
    query = User.objects.all()
    if lock:
        query = query.select_for_update()
    try:
        return query.only("status_version").get(pk=target_id).status_version
    except User.DoesNotExist as exc:
        raise NotFound from exc


def _subscription_version(user, context: AdminContext, target_id, lock):
    return scoped_subscription_or_404(user, context, target_id, lock=lock).version


def handle_subscription_open(context):
    admin_context = _subscription_context(context.requester)
    application = scoped_application_or_404(context.requester, admin_context, context.target_id)
    before = {"status": application.status, "version": application.version}
    subscription, application, flags = activate_application(
        requester=context.requester,
        admin_context=admin_context,
        application_id=context.target_id,
        expected_version=context.target_version,
        selected_plan_version_id=context.payload.get("selected_plan_version_id"),
        confirm_unavailable=context.payload.get("confirm_unavailable", False),
        unavailable_reason=context.payload.get("unavailable_reason", ""),
        confirm_version_override=context.payload.get("confirm_version_override", False),
        override_reason=context.payload.get("override_reason", ""),
        opening_note=context.payload.get("opening_note", ""),
        request_id=context.request.request_id,
    )
    after = {"status": application.status, "version": application.version}
    return HandlerResult(
        before,
        after,
        {
            "subscription_id": str(subscription.pk),
            "application_id": str(application.pk),
            "status": subscription.status,
            **flags,
        },
        subscription.user,
    )


def handle_subscription_grant_trial(context):
    admin_context = _subscription_context(context.requester)
    user = scoped_customer_or_404(context.requester, admin_context, context.target_id)
    before = {"status_version": user.status_version, "trial_granted": False}
    subscription = grant_trial(
        requester=context.requester,
        admin_context=admin_context,
        user_id=context.target_id,
        expected_status_version=context.target_version,
        plan_id=context.payload["plan_id"],
        opening_note=context.payload.get("opening_note", ""),
        request_id=context.request.request_id,
    )
    after = {"status_version": user.status_version, "trial_granted": True}
    return HandlerResult(
        before,
        after,
        {"subscription_id": str(subscription.pk), "status": subscription.status},
        subscription.user,
    )


def handle_subscription_terminate(context):
    admin_context = _subscription_context(context.requester)
    subscription = scoped_subscription_or_404(context.requester, admin_context, context.target_id)
    before = {"status": subscription.status, "version": subscription.version}
    subscription = terminate_subscription(
        requester=context.requester,
        admin_context=admin_context,
        subscription_id=context.target_id,
        expected_version=context.target_version,
        reason=context.payload["reason"],
        request_id=context.request.request_id,
    )
    after = {"status": subscription.status, "version": subscription.version}
    return HandlerResult(
        before,
        after,
        {"subscription_id": str(subscription.pk), **after},
        subscription.user,
    )


PLAN_HANDLER_SPECS = {
    "plan.create": HandlerSpec(
        "plans.create", False, PlanCreatePayloadSerializer, _new_plan_version, handle_plan_create
    ),
    "plan.update": HandlerSpec(
        "plans.update", False, PlanUpdatePayloadSerializer, _plan_version, handle_plan_update
    ),
    "plan.copy": HandlerSpec(
        "plans.copy", False, PlanCopyPayloadSerializer, _plan_version, handle_plan_copy
    ),
    "plan.version.create": HandlerSpec(
        "plan_versions.create",
        False,
        PlanVersionCreatePayloadSerializer,
        _plan_version,
        handle_plan_version_create,
    ),
    "plan.version.update": HandlerSpec(
        "plan_versions.update",
        False,
        PlanVersionUpdatePayloadSerializer,
        _plan_version_record_version,
        handle_plan_version_update,
    ),
    "plan.version.publish": HandlerSpec(
        "plan_versions.publish",
        False,
        PlanPublishPayloadSerializer,
        _plan_version_record_version,
        handle_plan_version_publish,
    ),
    "plan.online": HandlerSpec(
        "plans.online", False, EmptyPlanPayloadSerializer, _plan_version, handle_plan_online
    ),
    "plan.offline": HandlerSpec(
        "plans.offline", False, EmptyPlanPayloadSerializer, _plan_version, handle_plan_offline
    ),
    "plan.archive": HandlerSpec(
        "plans.archive", False, EmptyPlanPayloadSerializer, _plan_version, handle_plan_archive
    ),
    "plan.version.retire": HandlerSpec(
        "plan_versions.retire",
        False,
        EmptyPlanPayloadSerializer,
        _plan_version_record_version,
        handle_plan_version_retire,
    ),
    "plan_application.contact": HandlerSpec(
        "plan_applications.contact",
        False,
        EmptyPlanPayloadSerializer,
        _application_version,
        handle_plan_application_contact,
    ),
    "plan_application.close": HandlerSpec(
        "plan_applications.close",
        False,
        EmptyPlanPayloadSerializer,
        _application_version,
        handle_plan_application_close,
    ),
    "subscription.open": HandlerSpec(
        "subscriptions.open",
        False,
        OpenSubscriptionPayloadSerializer,
        _application_version,
        handle_subscription_open,
    ),
    "subscription.grant_trial": HandlerSpec(
        "subscriptions.grant_trial",
        False,
        GrantTrialPayloadSerializer,
        _customer_status_version,
        handle_subscription_grant_trial,
    ),
    "subscription.terminate": HandlerSpec(
        "subscriptions.terminate",
        False,
        TerminateSubscriptionPayloadSerializer,
        _subscription_version,
        handle_subscription_terminate,
    ),
}

PLAN_HANDLER_REGISTRY = {
    action_key: spec.execute for action_key, spec in PLAN_HANDLER_SPECS.items()
}
