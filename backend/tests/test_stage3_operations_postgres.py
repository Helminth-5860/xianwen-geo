from types import SimpleNamespace

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from rest_framework.exceptions import Throttled

from apps.operations.models import (
    CustomerContactLog,
    ReleaseEvidence,
    SupportViewAuditLog,
    SupportViewRequest,
)
from apps.operations.services import enforce_rate_limit
from apps.users.models import User

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="PostgreSQL-specific Stage 3 evidence requires PostgreSQL.",
    ),
]


def _assert_database_rejects(sql, params):
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(sql, params)


def test_stage3_tables_and_append_only_triggers_are_installed():
    expected_tables = {
        "customer_statuses",
        "customer_profiles",
        "customer_tags",
        "customer_tag_links",
        "customer_contact_logs",
        "customer_followups",
        "announcements",
        "user_feedback",
        "support_view_requests",
        "support_view_audit_logs",
        "system_alerts",
        "backup_records",
        "retention_jobs",
        "release_evidence",
    }
    expected_triggers = {
        "customer_contact_logs_append_only",
        "support_view_audit_logs_append_only",
        "release_evidence_append_only",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() "
            "AND tablename = ANY(%s)",
            [sorted(expected_tables)],
        )
        tables = {row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
        triggers = {row[0] for row in cursor.fetchall()}
    assert tables == expected_tables
    assert expected_triggers.issubset(triggers)


def test_stage3_append_only_evidence_rejects_raw_sql_mutation():
    admin = User.objects.create_superuser(
        phone="13900000001", nickname="Stage3 PG 管理员", password="Correct-Horse-2026!"
    )
    customer = User.objects.create_user(
        phone="13800000001", nickname="Stage3 PG 客户", password="Correct-Horse-2026!"
    )
    contact = CustomerContactLog.objects.create(
        customer=customer,
        actor=admin.admin_profile,
        contacted_at=timezone.now(),
        method="phone",
        content="append-only evidence",
    )
    support = SupportViewRequest.objects.create(
        requester=admin.admin_profile,
        customer=customer,
        reason="validate append-only access audit",
        status=SupportViewRequest.Status.ACTIVE,
        expires_at=timezone.now() + timezone.timedelta(minutes=10),
    )
    access = SupportViewAuditLog.objects.create(
        support_request=support,
        actor=admin,
        page_key="summary",
        outcome="allowed",
        request_id=admin.pk,
    )
    evidence = ReleaseEvidence.objects.create(
        environment="staging",
        evidence_key="deepseek_geo_detection",
        deploy_sha="1" * 40,
        safe_summary={"code": "PASSED"},
        observed_at=timezone.now(),
        expires_at=timezone.now() + timezone.timedelta(hours=1),
    )

    _assert_database_rejects(
        "UPDATE customer_contact_logs SET content = %s WHERE id = %s",
        ["tampered", contact.pk],
    )
    _assert_database_rejects(
        "DELETE FROM support_view_audit_logs WHERE id = %s",
        [access.pk],
    )
    _assert_database_rejects(
        "UPDATE release_evidence SET safe_summary = %s WHERE id = %s",
        ['{"code":"TAMPERED"}', evidence.pk],
    )


def test_stage3_rate_limit_uses_isolated_redis_and_fails_closed_at_limit():
    customer = User.objects.create_user(
        phone="13800000003", nickname="Stage3 Redis 客户", password="Correct-Horse-2026!"
    )
    request = SimpleNamespace(user=customer)
    enforce_rate_limit(request=request, scope="stage3-postgres-suite", limit=1)
    with pytest.raises(Throttled):
        enforce_rate_limit(request=request, scope="stage3-postgres-suite", limit=1)
