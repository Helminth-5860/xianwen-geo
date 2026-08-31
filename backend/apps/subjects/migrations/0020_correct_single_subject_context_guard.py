from django.db import migrations

CORRECT_CONTEXT_GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION subjects_assert_context(p_user_id uuid) RETURNS void AS $$
DECLARE
    v_current_subject_id uuid;
BEGIN
    SELECT current_subject_id INTO v_current_subject_id
    FROM subject_contexts
    WHERE user_id = p_user_id;
    IF NOT FOUND OR v_current_subject_id IS NULL THEN
        RETURN;
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM subjects s
        JOIN users u ON u.id = p_user_id
        WHERE s.id = v_current_subject_id
          AND s.status = 'active'
          AND (
              (s.tenant_id IS NOT NULL AND s.tenant_id = u.tenant_id) OR
              (s.tenant_id IS NULL AND s.user_id = p_user_id)
          )
    ) THEN
        RAISE EXCEPTION 'SUBJECT_CONTEXT_INVALID'
            USING ERRCODE = 'check_violation';
    END IF;
END;
$$ LANGUAGE plpgsql;
"""


def correct_context_guard(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CORRECT_CONTEXT_GUARD_SQL)


class Migration(migrations.Migration):
    dependencies = [("subjects", "0019_subjectidentitycorrectionevent_and_more")]

    operations = [
        migrations.RunPython(correct_context_guard, migrations.RunPython.noop),
    ]
