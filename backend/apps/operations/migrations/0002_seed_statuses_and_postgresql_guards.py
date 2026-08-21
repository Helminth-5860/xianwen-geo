from django.db import migrations


BUILTIN_STATUSES = (
    ("pending_review", "待审核", 10),
    ("review_rejected", "审核未通过", 20),
    ("pending_plan", "待开通", 30),
    ("trial", "试用中", 40),
    ("formal", "正式客户", 50),
    ("expiring", "即将到期", 60),
    ("expired", "已到期", 70),
    ("suspended", "暂停使用", 80),
    ("lost", "已流失", 90),
    ("cancelled", "已注销", 100),
)


def seed_statuses(apps, schema_editor):
    CustomerStatus = apps.get_model("operations", "CustomerStatus")
    for key, name, sort_order in BUILTIN_STATUSES:
        CustomerStatus.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "sort_order": sort_order,
                "is_builtin": True,
                "state": "active",
            },
        )


def create_postgresql_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        CREATE OR REPLACE FUNCTION operations_append_only_guard()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'stage3 operational evidence is append-only';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER customer_contact_logs_append_only
        BEFORE UPDATE OR DELETE ON customer_contact_logs
        FOR EACH ROW EXECUTE FUNCTION operations_append_only_guard();

        CREATE TRIGGER support_view_audit_logs_append_only
        BEFORE UPDATE OR DELETE ON support_view_audit_logs
        FOR EACH ROW EXECUTE FUNCTION operations_append_only_guard();
        """
    )


def drop_postgresql_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        DROP TRIGGER IF EXISTS customer_contact_logs_append_only ON customer_contact_logs;
        DROP TRIGGER IF EXISTS support_view_audit_logs_append_only ON support_view_audit_logs;
        DROP FUNCTION IF EXISTS operations_append_only_guard();
        """
    )


class Migration(migrations.Migration):
    dependencies = [("operations", "0001_initial")]
    operations = [
        migrations.RunPython(seed_statuses, migrations.RunPython.noop),
        migrations.RunPython(create_postgresql_guards, drop_postgresql_guards),
    ]
