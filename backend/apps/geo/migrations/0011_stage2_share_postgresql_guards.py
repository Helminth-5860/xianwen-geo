from django.db import migrations


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    sql = r"""
    CREATE OR REPLACE FUNCTION report_share_guard() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'report shares cannot be deleted'; END IF;
      IF NEW.report_id IS DISTINCT FROM OLD.report_id OR
         NEW.user_id IS DISTINCT FROM OLD.user_id OR
         NEW.subject_id IS DISTINCT FROM OLD.subject_id OR
         NEW.token_digest IS DISTINCT FROM OLD.token_digest OR
         NEW.report_snapshot IS DISTINCT FROM OLD.report_snapshot OR
         NEW.report_snapshot_digest IS DISTINCT FROM OLD.report_snapshot_digest OR
         NEW.brand_snapshot IS DISTINCT FROM OLD.brand_snapshot OR
         NEW.password_hash IS DISTINCT FROM OLD.password_hash OR
         NEW.expires_at IS DISTINCT FROM OLD.expires_at OR
         NEW.created_at IS DISTINCT FROM OLD.created_at
      THEN RAISE EXCEPTION 'report share snapshot is immutable'; END IF;
      IF OLD.closed_at IS NOT NULL AND NEW.closed_at IS DISTINCT FROM OLD.closed_at
      THEN RAISE EXCEPTION 'closed report share is immutable'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    DROP TRIGGER IF EXISTS report_shares_guard ON report_shares;
    CREATE TRIGGER report_shares_guard BEFORE UPDATE OR DELETE ON report_shares
      FOR EACH ROW EXECUTE FUNCTION report_share_guard();

    CREATE OR REPLACE FUNCTION report_share_access_log_guard() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'report share access log is append-only'; END; $$ LANGUAGE plpgsql;
    DROP TRIGGER IF EXISTS report_share_access_logs_guard ON report_share_access_logs;
    CREATE TRIGGER report_share_access_logs_guard BEFORE UPDATE OR DELETE ON report_share_access_logs
      FOR EACH ROW EXECUTE FUNCTION report_share_access_log_guard();
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(sql)


class Migration(migrations.Migration):
    dependencies = [("geo", "0010_reportshare_reportshareaccesslog_and_more")]
    operations = [migrations.RunPython(install_guards, migrations.RunPython.noop)]
