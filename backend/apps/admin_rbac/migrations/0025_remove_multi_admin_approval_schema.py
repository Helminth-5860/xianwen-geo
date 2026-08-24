from django.db import migrations


def preserve_approval_history(apps, schema_editor):
    ApprovalRequest = apps.get_model("admin_rbac", "ApprovalRequest")
    AuditEvent = apps.get_model("admin_rbac", "AuditEvent")

    for approval in ApprovalRequest.objects.all().iterator():
        history = {
            "legacy_approval_status": approval.status,
            "legacy_safe_summary": approval.safe_summary,
        }
        events = AuditEvent.objects.filter(approval_request_id=approval.pk)
        if events.exists():
            for event in events.iterator():
                safe_after = dict(event.safe_after or {})
                safe_after.update(history)
                event.safe_after = safe_after
                event.save(update_fields=("safe_after",))
            continue

        AuditEvent.objects.create(
            category="retired_approval_history",
            action_key=approval.action_key,
            outcome=approval.status,
            actor_id=approval.approved_by_id or approval.rejected_by_id or approval.requester_id,
            requester_id=approval.requester_id,
            approver_id=approval.approved_by_id,
            target_type=approval.target_type,
            target_id=approval.target_id,
            request_id=approval.request_id,
            approval_request_id=approval.pk,
            safe_before={},
            safe_after=history,
            stable_error_code=approval.stable_error_code,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("admin_rbac", "0024_retire_multi_admin_approval"),
        ("plans", "0015_remove_subscription_change_approval"),
        ("subjects", "0015_remove_catalog_revision_approval"),
    ]

    operations = [
        migrations.RunPython(preserve_approval_history, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="auditevent",
            name="approval_request",
        ),
        migrations.RemoveField(
            model_name="auditevent",
            name="approver",
        ),
        migrations.DeleteModel(
            name="ApprovalRequest",
        ),
    ]
