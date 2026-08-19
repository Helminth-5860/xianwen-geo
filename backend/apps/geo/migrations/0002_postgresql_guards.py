from django.db import migrations


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION geo_reject_history_delete() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'GEO detection history cannot be deleted';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION geo_reject_immutable_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'GEO immutable evidence cannot be changed';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS geo_detection_jobs_no_delete ON geo_detection_jobs;
CREATE TRIGGER geo_detection_jobs_no_delete
BEFORE DELETE ON geo_detection_jobs
FOR EACH ROW EXECUTE FUNCTION geo_reject_history_delete();

DROP TRIGGER IF EXISTS geo_detection_snapshots_immutable ON geo_detection_snapshots;
CREATE TRIGGER geo_detection_snapshots_immutable
BEFORE UPDATE OR DELETE ON geo_detection_snapshots
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

DROP TRIGGER IF EXISTS geo_question_snapshots_immutable ON geo_detection_question_snapshots;
CREATE TRIGGER geo_question_snapshots_immutable
BEFORE UPDATE OR DELETE ON geo_detection_question_snapshots
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

DROP TRIGGER IF EXISTS geo_model_runs_no_delete ON geo_detection_model_runs;
CREATE TRIGGER geo_model_runs_no_delete
BEFORE DELETE ON geo_detection_model_runs
FOR EACH ROW EXECUTE FUNCTION geo_reject_history_delete();

DROP TRIGGER IF EXISTS geo_model_calls_no_delete ON model_calls;
CREATE TRIGGER geo_model_calls_no_delete
BEFORE DELETE ON model_calls
FOR EACH ROW EXECUTE FUNCTION geo_reject_history_delete();

DROP TRIGGER IF EXISTS geo_model_call_attempts_no_delete ON model_call_attempts;
CREATE TRIGGER geo_model_call_attempts_no_delete
BEFORE DELETE ON model_call_attempts
FOR EACH ROW EXECUTE FUNCTION geo_reject_history_delete();

DROP TRIGGER IF EXISTS geo_model_responses_immutable ON model_responses;
CREATE TRIGGER geo_model_responses_immutable
BEFORE UPDATE OR DELETE ON model_responses
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS geo_detection_jobs_no_delete ON geo_detection_jobs;
DROP TRIGGER IF EXISTS geo_detection_snapshots_immutable ON geo_detection_snapshots;
DROP TRIGGER IF EXISTS geo_question_snapshots_immutable ON geo_detection_question_snapshots;
DROP TRIGGER IF EXISTS geo_model_runs_no_delete ON geo_detection_model_runs;
DROP TRIGGER IF EXISTS geo_model_calls_no_delete ON model_calls;
DROP TRIGGER IF EXISTS geo_model_call_attempts_no_delete ON model_call_attempts;
DROP TRIGGER IF EXISTS geo_model_responses_immutable ON model_responses;
DROP FUNCTION IF EXISTS geo_reject_history_delete();
DROP FUNCTION IF EXISTS geo_reject_immutable_change();
"""


def install(apps, schema_editor):
    del apps
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD_SQL)


def reverse(apps, schema_editor):
    del apps
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("geo", "0001_initial")]
    operations = [migrations.RunPython(install, reverse)]
