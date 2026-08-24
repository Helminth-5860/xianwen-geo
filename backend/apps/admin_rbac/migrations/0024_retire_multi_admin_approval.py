from django.db import migrations, models
from django.utils import timezone


RETIRED_PERMISSION_KEYS = (
    "menu.admin.approvals",
    "approvals.list",
    "approvals.view",
    "approvals.request",
    "approvals.approve",
    "approvals.reject",
    "approvals.cancel",
)

CONFIRM_ACTION_KEYS = {
    "subscription.open",
    "subscription.grant_trial",
    "subscription.terminate",
    "subscription.change",
    "subscription.change.cancel",
    "quota.grant",
    "quota.compensate",
    "quota.manual_deduct",
    "subject_risk.catalog.publish",
}


def retire_multi_admin_approval(apps, schema_editor):
    AdminPermission = apps.get_model("admin_rbac", "AdminPermission")
    AdminRolePermission = apps.get_model("admin_rbac", "AdminRolePermission")
    ApprovalRequest = apps.get_model("admin_rbac", "ApprovalRequest")
    RiskAction = apps.get_model("admin_rbac", "RiskAction")
    RiskPolicy = apps.get_model("admin_rbac", "RiskPolicy")

    AdminRolePermission.objects.filter(permission__key__in=RETIRED_PERMISSION_KEYS).delete()
    AdminPermission.objects.filter(key__in=RETIRED_PERMISSION_KEYS).delete()

    for action in RiskAction.objects.all().iterator():
        replacement_mode = "confirm" if action.key in CONFIRM_ACTION_KEYS else "password"
        supported_modes = [
            replacement_mode if mode == "two_person" else mode for mode in action.supported_modes
        ]
        if not supported_modes:
            supported_modes = [replacement_mode]
        action.supported_modes = list(dict.fromkeys(supported_modes))
        if action.default_mode == "two_person":
            action.default_mode = replacement_mode
        if action.minimum_mode == "two_person":
            action.minimum_mode = replacement_mode
        action.catalog_version = 8
        action.save(
            update_fields=(
                "supported_modes",
                "default_mode",
                "minimum_mode",
                "catalog_version",
                "updated_at",
            )
        )

    for policy in RiskPolicy.objects.filter(current_mode="two_person").select_related("action"):
        policy.current_mode = "confirm" if policy.action.key in CONFIRM_ACTION_KEYS else "password"
        policy.version += 1
        policy.save(update_fields=("current_mode", "version", "updated_at"))

    ApprovalRequest.objects.filter(status="pending").update(
        status="cancelled",
        cancelled_at=timezone.now(),
        stable_error_code="APPROVAL_FLOW_RETIRED",
    )


class Migration(migrations.Migration):
    dependencies = [("admin_rbac", "0023_admin_registration_channel_key")]

    operations = [
        migrations.RunPython(retire_multi_admin_approval, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="riskpolicy",
            name="risk_policy_valid_mode",
        ),
        migrations.AddConstraint(
            model_name="riskpolicy",
            constraint=models.CheckConstraint(
                condition=models.Q(current_mode__in=("confirm", "password")),
                name="risk_policy_valid_mode",
            ),
        ),
    ]
