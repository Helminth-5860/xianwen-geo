from django.db import migrations, models


def remove_account_review_records(apps, schema_editor):
    Notification = apps.get_model("users", "Notification")
    UserStatusEvent = apps.get_model("users", "UserStatusEvent")
    Notification.objects.filter(
        notification_type__in=("approval_approved", "approval_rejected")
    ).delete()
    UserStatusEvent.objects.filter(status_domain="approval").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0011_tenant_user_tenant"),
    ]

    operations = [
        migrations.RunPython(remove_account_review_records, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="userstatusevent",
            name="status_event_domain_values_valid",
        ),
        migrations.AlterField(
            model_name="user",
            name="account_status",
            field=models.CharField(
                choices=[
                    ("active", "正常"),
                    ("frozen", "禁用"),
                    ("cancel_pending", "注销冷静期"),
                    ("cancelled", "已注销"),
                ],
                db_index=True,
                default="active",
                max_length=16,
            ),
        ),
        migrations.RemoveField(model_name="user", name="approval_reason"),
        migrations.RemoveField(model_name="user", name="approval_status"),
        migrations.RemoveField(model_name="user", name="approved_at"),
        migrations.RemoveField(model_name="user", name="approved_by"),
        migrations.AlterField(
            model_name="userstatusevent",
            name="status_domain",
            field=models.CharField(choices=[("account", "账号状态")], max_length=16),
        ),
        migrations.AlterField(
            model_name="userstatusevent",
            name="event_type",
            field=models.CharField(
                choices=[("frozen", "账号禁用"), ("unfrozen", "账号恢复")],
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="userstatusevent",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    status_domain="account",
                    from_value__in=["active", "frozen", "cancel_pending", "cancelled"],
                    to_value__in=["active", "frozen", "cancel_pending", "cancelled"],
                ),
                name="status_event_domain_values_valid",
            ),
        ),
        migrations.AlterField(
            model_name="notification",
            name="notification_type",
            field=models.CharField(
                choices=[
                    ("account_frozen", "账号禁用"),
                    ("account_unfrozen", "账号恢复"),
                    ("plan_application_submitted", "套餐申请已提交"),
                    ("plan_application_contacted", "套餐申请已联系"),
                    ("plan_application_closed", "套餐申请已关闭"),
                    ("plan_application_cancelled", "套餐申请已取消"),
                    ("plan_application_activated", "套餐申请已开通"),
                    ("subscription_trial_granted", "试用套餐已发放"),
                    ("subscription_expired", "套餐已到期"),
                    ("subscription_terminated", "套餐已终止"),
                    ("subscription_renewed", "Subscription renewed"),
                    ("subject_review_approved", "主体资料审核通过"),
                    ("subject_review_rejected", "主体资料审核拒绝"),
                    ("document_parse_succeeded", "??????"),
                    ("document_parse_failed", "??????"),
                    ("web_import_succeeded", "网页导入完成"),
                    ("web_import_failed", "网页导入失败"),
                ],
                max_length=32,
            ),
        ),
    ]
