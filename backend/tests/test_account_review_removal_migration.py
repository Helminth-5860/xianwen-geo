import uuid

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_forward_migration_removes_account_review_schema_and_records():
    executor = MigrationExecutor(connection)
    try:
        executor.migrate([("users", "0011_tenant_user_tenant")])
        old_apps = executor.loader.project_state([("users", "0011_tenant_user_tenant")]).apps
        User = old_apps.get_model("users", "User")
        UserStatusEvent = old_apps.get_model("users", "UserStatusEvent")
        Notification = old_apps.get_model("users", "Notification")

        user = User.objects.create(
            phone="+8613800138000",
            nickname="迁移验证用户",
            password="!",
            approval_status="rejected",
            approval_reason="历史拒绝原因",
            account_status="active",
            is_active=True,
        )
        approval_event = UserStatusEvent.objects.create(
            user=user,
            status_domain="approval",
            event_type="rejected",
            from_value="pending",
            to_value="rejected",
            reason="历史拒绝原因",
            request_id=uuid.uuid4(),
        )
        account_event = UserStatusEvent.objects.create(
            user=user,
            status_domain="account",
            event_type="frozen",
            from_value="active",
            to_value="frozen",
            reason="",
            request_id=uuid.uuid4(),
        )
        Notification.objects.create(
            recipient=user,
            notification_type="approval_rejected",
            title="历史审核通知",
            safe_summary="历史安全摘要",
            related_status_event=approval_event,
        )
        Notification.objects.create(
            recipient=user,
            notification_type="account_frozen",
            title="账号已禁用",
            safe_summary="账号状态通知",
            related_status_event=account_event,
        )

        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

        from apps.users.models import Notification as CurrentNotification
        from apps.users.models import User as CurrentUser
        from apps.users.models import UserStatusEvent as CurrentUserStatusEvent

        migrated = CurrentUser.objects.get(pk=user.pk)
        assert migrated.account_status == "active"
        assert migrated.is_active is True
        assert not CurrentUserStatusEvent.objects.filter(status_domain="approval").exists()
        assert CurrentUserStatusEvent.objects.filter(pk=account_event.pk).exists()
        assert not CurrentNotification.objects.filter(
            notification_type="approval_rejected"
        ).exists()
        assert CurrentNotification.objects.filter(notification_type="account_frozen").exists()

        with connection.cursor() as cursor:
            user_columns = {
                column.name
                for column in connection.introspection.get_table_description(cursor, "users")
            }
        assert {
            "approval_status",
            "approval_reason",
            "approved_at",
            "approved_by_id",
        }.isdisjoint(user_columns)
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
