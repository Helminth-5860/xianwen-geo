import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from apps.users.models import User


@pytest.mark.django_db(transaction=True)
def test_existing_approval_data_is_preserved_in_audit_before_schema_removal():
    executor = MigrationExecutor(connection)
    unaffected_leaves = [
        node
        for node in executor.loader.graph.leaf_nodes()
        if node[0] not in {"admin_rbac", "plans", "subjects"}
    ]
    old_targets = unaffected_leaves + [
        ("admin_rbac", "0023_admin_registration_channel_key"),
        ("plans", "0013_lifecycle_postgresql_guards"),
        ("subjects", "0013_subject_enrichment_postgresql_guards"),
    ]

    try:
        executor.migrate(old_targets)
        old_apps = executor.loader.project_state(old_targets).apps
        ApprovalRequest = old_apps.get_model("admin_rbac", "ApprovalRequest")
        AuditEvent = old_apps.get_model("admin_rbac", "AuditEvent")
        RiskAction = old_apps.get_model("admin_rbac", "RiskAction")

        requester = User.objects.create_superuser(
            phone="13900139998",
            nickname="迁移验证管理员",
            password="Migration-Test-2026!",
        )
        action, _created = RiskAction.objects.get_or_create(
            key="admin.disable",
            defaults={
                "name": "停用管理员",
                "module": "admins",
                "target_type": "admin_profile",
                "supported_modes": ["password", "two_person"],
                "default_mode": "two_person",
                "minimum_mode": "password",
                "handler_key": "admin.disable",
                "status": "active",
                "catalog_version": 1,
            },
        )
        request_id = uuid.uuid4()
        target_id = uuid.uuid4()
        approval = ApprovalRequest.objects.create(
            action=action,
            action_key=action.key,
            policy_version=1,
            requester_id=requester.pk,
            target_type="admin_profile",
            target_id=target_id,
            target_version=1,
            sanitized_payload={},
            payload_digest="a" * 64,
            safe_summary="历史操作摘要",
            expires_at=timezone.now() + timedelta(hours=1),
            request_id=request_id,
        )
        AuditEvent.objects.create(
            category="high_risk_action",
            action_key=action.key,
            outcome="requested",
            actor_id=requester.pk,
            requester_id=requester.pk,
            target_type="admin_profile",
            target_id=target_id,
            request_id=request_id,
            approval_request_id=approval.pk,
            safe_before={},
            safe_after={"status": "requested"},
        )

        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

        from apps.admin_rbac.models import AuditEvent as CurrentAuditEvent

        event = CurrentAuditEvent.objects.get(request_id=request_id)
        assert event.safe_after["legacy_approval_status"] == "cancelled"
        assert event.safe_after["legacy_safe_summary"] == "历史操作摘要"
        with connection.cursor() as cursor:
            assert "approval_requests" not in connection.introspection.table_names(cursor)
            audit_columns = {
                column.name
                for column in connection.introspection.get_table_description(cursor, "audit_events")
            }
        assert {"approval_request_id", "approver_id"}.isdisjoint(audit_columns)
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
