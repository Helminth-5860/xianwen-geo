from django.db import migrations


FORWARD = r"""
CREATE OR REPLACE FUNCTION subject_enrichment_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'subject enrichment evidence is immutable';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subject_enrichment_job_guard() RETURNS trigger AS $$
DECLARE s RECORD;
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'subject enrichment jobs cannot be deleted'; END IF;
    SELECT user_id, version, schema_digest, schema_snapshot_format_version, current_version_id
      INTO s FROM subjects WHERE id = NEW.subject_id;
    IF NOT FOUND OR NEW.user_id <> s.user_id THEN RAISE EXCEPTION 'subject enrichment ownership mismatch'; END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.subject_object_version_at_create <> s.version
           OR NEW.schema_digest <> s.schema_digest
           OR NEW.schema_snapshot_format_version <> s.schema_snapshot_format_version
           OR NEW.current_formal_subject_version_id_at_create IS DISTINCT FROM s.current_version_id THEN
            RAISE EXCEPTION 'subject enrichment job binding mismatch';
        END IF;
    ELSE
        IF NEW.user_id <> OLD.user_id OR NEW.subject_id <> OLD.subject_id
           OR NEW.subject_object_version_at_create <> OLD.subject_object_version_at_create
           OR NEW.current_formal_subject_version_id_at_create IS DISTINCT FROM OLD.current_formal_subject_version_id_at_create
           OR NEW.schema_digest <> OLD.schema_digest
           OR NEW.schema_snapshot_format_version <> OLD.schema_snapshot_format_version
           OR NEW.target_manifest <> OLD.target_manifest OR NEW.input_subject_values <> OLD.input_subject_values
           OR NEW.provider_key <> OLD.provider_key OR NEW.model_key <> OLD.model_key
           OR NEW.adapter_version <> OLD.adapter_version OR NEW.prompt_version <> OLD.prompt_version
           OR NEW.input_digest <> OLD.input_digest OR NEW.idempotency_key_version <> OLD.idempotency_key_version
           OR NEW.idempotency_key_digest <> OLD.idempotency_key_digest OR NEW.request_digest <> OLD.request_digest
           OR NEW.request_id IS DISTINCT FROM OLD.request_id OR NEW.correlation_id IS DISTINCT FROM OLD.correlation_id THEN
            RAISE EXCEPTION 'subject enrichment immutable job binding changed';
        END IF;
        IF OLD.status IN ('succeeded','failed') THEN
            RAISE EXCEPTION 'subject enrichment terminal job is immutable';
        END IF;
        IF OLD.status <> NEW.status AND NOT (
            (OLD.status='queued' AND NEW.status='running') OR
            (OLD.status='running' AND NEW.status IN ('retry_wait','succeeded','failed')) OR
            (OLD.status='retry_wait' AND NEW.status='running')
        ) THEN RAISE EXCEPTION 'invalid subject enrichment state transition'; END IF;
    END IF;
    IF NEW.status='succeeded' THEN
        IF NEW.output_digest='' OR (
            SELECT count(*) FROM subject_enrichment_suggestions WHERE job_id=NEW.id
        ) <> jsonb_array_length(NEW.target_manifest) THEN
            RAISE EXCEPTION 'succeeded enrichment job result incomplete';
        END IF;
    ELSIF NEW.status='failed' AND EXISTS (
        SELECT 1 FROM subject_enrichment_suggestions WHERE job_id=NEW.id
    ) THEN RAISE EXCEPTION 'failed enrichment job cannot have suggestions'; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subject_enrichment_source_guard() RETURNS trigger AS $$
DECLARE j RECORD; p RECORD; current_id uuid;
BEGIN
    SELECT user_id, subject_id INTO j FROM subject_enrichment_jobs WHERE id = NEW.job_id;
    IF NOT FOUND OR NEW.user_id <> j.user_id OR NEW.subject_id <> j.subject_id THEN
        RAISE EXCEPTION 'subject enrichment source ownership mismatch';
    END IF;
    IF NEW.source_type = 'document' THEN
        SELECT user_id, subject_id, source, content_digest, document_version_id INTO p
          FROM document_parsed_versions WHERE id = NEW.document_parsed_version_id;
        IF NOT FOUND OR p.user_id <> NEW.user_id OR p.subject_id <> NEW.subject_id
           OR p.source <> 'user_confirmation' OR p.content_digest <> NEW.content_digest THEN
            RAISE EXCEPTION 'invalid confirmed document source';
        END IF;
        SELECT current_confirmed_version_id INTO current_id FROM document_parse_states WHERE document_version_id = p.document_version_id;
        IF current_id IS DISTINCT FROM NEW.document_parsed_version_id THEN RAISE EXCEPTION 'document source is not current confirmed'; END IF;
    ELSIF NEW.source_type = 'web' THEN
        SELECT user_id, subject_id, source, content_digest, import_record_id INTO p
          FROM web_source_parsed_versions WHERE id = NEW.web_parsed_version_id;
        IF NOT FOUND OR p.user_id <> NEW.user_id OR p.subject_id <> NEW.subject_id
           OR p.source <> 'user_confirmation' OR p.content_digest <> NEW.content_digest THEN
            RAISE EXCEPTION 'invalid confirmed web source';
        END IF;
        SELECT current_confirmed_version_id INTO current_id FROM web_source_imports WHERE id = p.import_record_id AND status='succeeded';
        IF current_id IS DISTINCT FROM NEW.web_parsed_version_id THEN RAISE EXCEPTION 'web source is not current confirmed'; END IF;
    ELSE RAISE EXCEPTION 'invalid enrichment source type'; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subject_enrichment_suggestion_guard() RETURNS trigger AS $$
DECLARE targets jsonb;
BEGIN
    SELECT target_manifest INTO targets FROM subject_enrichment_jobs WHERE id = NEW.job_id;
    IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(targets) e WHERE e->>'field_key'=NEW.field_key) THEN
        RAISE EXCEPTION 'suggestion field is outside target manifest';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subject_enrichment_citation_guard() RETURNS trigger AS $$
DECLARE sj uuid; so uuid;
BEGIN
    SELECT job_id INTO sj FROM subject_enrichment_suggestions WHERE id=NEW.suggestion_id;
    SELECT job_id INTO so FROM subject_enrichment_sources WHERE id=NEW.source_id;
    IF sj IS NULL OR so IS NULL OR sj <> so THEN RAISE EXCEPTION 'citation crosses enrichment jobs'; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subject_enrichment_decision_guard() RETURNS trigger AS $$
DECLARE confirmation_job uuid; suggestion_job uuid;
BEGIN
    SELECT job_id INTO confirmation_job FROM subject_enrichment_confirmations WHERE id=NEW.confirmation_id;
    SELECT job_id INTO suggestion_job FROM subject_enrichment_suggestions WHERE id=NEW.suggestion_id;
    IF confirmation_job IS NULL OR suggestion_job IS NULL OR confirmation_job<>suggestion_job THEN
        RAISE EXCEPTION 'decision crosses enrichment jobs';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subject_enrichment_confirmation_guard() RETURNS trigger AS $$
DECLARE j RECORD; s RECORD; suggestion_count integer; decision_count integer; accepted_count integer;
BEGIN
    SELECT user_id, subject_id, status, subject_object_version_at_create INTO j
      FROM subject_enrichment_jobs WHERE id=NEW.job_id;
    SELECT user_id, version, draft_values INTO s FROM subjects WHERE id=NEW.subject_id;
    IF NOT FOUND OR j.user_id<>NEW.user_id OR j.subject_id<>NEW.subject_id OR NEW.confirmed_by_id<>NEW.user_id
       OR j.status<>'succeeded' OR j.subject_object_version_at_create<>NEW.subject_version_before THEN
       RAISE EXCEPTION 'invalid enrichment confirmation binding';
    END IF;
    IF s.user_id<>NEW.user_id OR s.version<>NEW.subject_version_after
       OR NEW.subject_version_after NOT IN (NEW.subject_version_before, NEW.subject_version_before+1) THEN
       RAISE EXCEPTION 'invalid enrichment confirmation subject version';
    END IF;
    SELECT count(*) INTO suggestion_count FROM subject_enrichment_suggestions WHERE job_id=NEW.job_id;
    SELECT count(*), count(*) FILTER (WHERE d.accepted) INTO decision_count, accepted_count
      FROM subject_enrichment_decisions d JOIN subject_enrichment_suggestions sg ON sg.id=d.suggestion_id
      WHERE d.confirmation_id=NEW.id AND sg.job_id=NEW.job_id;
    IF decision_count<>suggestion_count THEN RAISE EXCEPTION 'confirmation decisions are incomplete'; END IF;
    IF accepted_count>0 AND NEW.subject_version_after<>NEW.subject_version_before+1 THEN RAISE EXCEPTION 'accepted enrichment must increment subject version'; END IF;
    IF accepted_count=0 AND NEW.subject_version_after<>NEW.subject_version_before THEN RAISE EXCEPTION 'all rejected enrichment must not increment subject version'; END IF;
    IF EXISTS (
        SELECT 1 FROM subject_enrichment_decisions d
        JOIN subject_enrichment_suggestions sg ON sg.id=d.suggestion_id
        WHERE d.confirmation_id=NEW.id AND d.accepted
          AND s.draft_values->sg.field_key IS DISTINCT FROM sg.suggested_value
    ) THEN RAISE EXCEPTION 'accepted enrichment value not applied to draft'; END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS subject_enrichment_job_guard_trg ON subject_enrichment_jobs;
CREATE TRIGGER subject_enrichment_job_guard_trg BEFORE INSERT OR UPDATE OR DELETE ON subject_enrichment_jobs FOR EACH ROW EXECUTE FUNCTION subject_enrichment_job_guard();
DROP TRIGGER IF EXISTS subject_enrichment_source_guard_trg ON subject_enrichment_sources;
CREATE TRIGGER subject_enrichment_source_guard_trg BEFORE INSERT ON subject_enrichment_sources FOR EACH ROW EXECUTE FUNCTION subject_enrichment_source_guard();
DROP TRIGGER IF EXISTS subject_enrichment_suggestion_guard_trg ON subject_enrichment_suggestions;
CREATE TRIGGER subject_enrichment_suggestion_guard_trg BEFORE INSERT ON subject_enrichment_suggestions FOR EACH ROW EXECUTE FUNCTION subject_enrichment_suggestion_guard();
DROP TRIGGER IF EXISTS subject_enrichment_citation_guard_trg ON subject_enrichment_suggestion_sources;
CREATE TRIGGER subject_enrichment_citation_guard_trg BEFORE INSERT ON subject_enrichment_suggestion_sources FOR EACH ROW EXECUTE FUNCTION subject_enrichment_citation_guard();
DROP TRIGGER IF EXISTS subject_enrichment_decision_guard_trg ON subject_enrichment_decisions;
CREATE TRIGGER subject_enrichment_decision_guard_trg BEFORE INSERT ON subject_enrichment_decisions FOR EACH ROW EXECUTE FUNCTION subject_enrichment_decision_guard();
DROP TRIGGER IF EXISTS subject_enrichment_confirmation_guard_trg ON subject_enrichment_confirmations;
CREATE CONSTRAINT TRIGGER subject_enrichment_confirmation_guard_trg AFTER INSERT ON subject_enrichment_confirmations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION subject_enrichment_confirmation_guard();

DROP TRIGGER IF EXISTS subject_enrichment_sources_immutable_trg ON subject_enrichment_sources;
CREATE TRIGGER subject_enrichment_sources_immutable_trg BEFORE UPDATE OR DELETE ON subject_enrichment_sources FOR EACH ROW EXECUTE FUNCTION subject_enrichment_immutable();

DROP TRIGGER IF EXISTS subject_enrichment_suggestions_immutable_trg ON subject_enrichment_suggestions;
CREATE TRIGGER subject_enrichment_suggestions_immutable_trg BEFORE UPDATE OR DELETE ON subject_enrichment_suggestions FOR EACH ROW EXECUTE FUNCTION subject_enrichment_immutable();

DROP TRIGGER IF EXISTS subject_enrichment_suggestion_sources_immutable_trg ON subject_enrichment_suggestion_sources;
CREATE TRIGGER subject_enrichment_suggestion_sources_immutable_trg BEFORE UPDATE OR DELETE ON subject_enrichment_suggestion_sources FOR EACH ROW EXECUTE FUNCTION subject_enrichment_immutable();

DROP TRIGGER IF EXISTS subject_enrichment_confirmations_immutable_trg ON subject_enrichment_confirmations;
CREATE TRIGGER subject_enrichment_confirmations_immutable_trg BEFORE UPDATE OR DELETE ON subject_enrichment_confirmations FOR EACH ROW EXECUTE FUNCTION subject_enrichment_immutable();

DROP TRIGGER IF EXISTS subject_enrichment_decisions_immutable_trg ON subject_enrichment_decisions;
CREATE TRIGGER subject_enrichment_decisions_immutable_trg BEFORE UPDATE OR DELETE ON subject_enrichment_decisions FOR EACH ROW EXECUTE FUNCTION subject_enrichment_immutable();

DROP TRIGGER IF EXISTS subject_enrichment_events_immutable_trg ON subject_enrichment_events;
CREATE TRIGGER subject_enrichment_events_immutable_trg BEFORE UPDATE OR DELETE ON subject_enrichment_events FOR EACH ROW EXECUTE FUNCTION subject_enrichment_immutable();
"""

REVERSE = r"""
DROP TRIGGER IF EXISTS subject_enrichment_job_guard_trg ON subject_enrichment_jobs;
DROP TRIGGER IF EXISTS subject_enrichment_source_guard_trg ON subject_enrichment_sources;
DROP TRIGGER IF EXISTS subject_enrichment_suggestion_guard_trg ON subject_enrichment_suggestions;
DROP TRIGGER IF EXISTS subject_enrichment_citation_guard_trg ON subject_enrichment_suggestion_sources;
DROP TRIGGER IF EXISTS subject_enrichment_decision_guard_trg ON subject_enrichment_decisions;
DROP TRIGGER IF EXISTS subject_enrichment_confirmation_guard_trg ON subject_enrichment_confirmations;
DROP TRIGGER IF EXISTS subject_enrichment_sources_immutable_trg ON subject_enrichment_sources;
DROP TRIGGER IF EXISTS subject_enrichment_suggestions_immutable_trg ON subject_enrichment_suggestions;
DROP TRIGGER IF EXISTS subject_enrichment_suggestion_sources_immutable_trg ON subject_enrichment_suggestion_sources;
DROP TRIGGER IF EXISTS subject_enrichment_confirmations_immutable_trg ON subject_enrichment_confirmations;
DROP TRIGGER IF EXISTS subject_enrichment_decisions_immutable_trg ON subject_enrichment_decisions;
DROP TRIGGER IF EXISTS subject_enrichment_events_immutable_trg ON subject_enrichment_events;
DROP FUNCTION IF EXISTS subject_enrichment_confirmation_guard();
DROP FUNCTION IF EXISTS subject_enrichment_decision_guard();
DROP FUNCTION IF EXISTS subject_enrichment_citation_guard();
DROP FUNCTION IF EXISTS subject_enrichment_suggestion_guard();
DROP FUNCTION IF EXISTS subject_enrichment_source_guard();
DROP FUNCTION IF EXISTS subject_enrichment_job_guard();
DROP FUNCTION IF EXISTS subject_enrichment_immutable();
"""


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD)


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE)


class Migration(migrations.Migration):
    dependencies = [("subjects", "0012_subject_enrichment_models")]
    operations = [migrations.RunPython(install_guards, remove_guards)]
