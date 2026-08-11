from django.db import migrations


INSTALL_SQL = r"""
CREATE OR REPLACE FUNCTION subjects_guard_risk_evidence() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'SUBJECT_RISK_EVIDENCE_IMMUTABLE';
    END IF;
    RAISE EXCEPTION 'SUBJECT_RISK_EVIDENCE_DELETE_FORBIDDEN';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_guard_risk_draft() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'SUBJECT_RISK_DRAFT_DELETE_FORBIDDEN';
    END IF;
    IF NEW.key IS DISTINCT FROM OLD.key THEN
        RAISE EXCEPTION 'SUBJECT_RISK_KEY_IMMUTABLE';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'SUBJECT_RISK_DRAFT_VERSION_CONFLICT';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_guard_review() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'SUBJECT_REVIEW_DELETE_FORBIDDEN';
    END IF;
    IF ROW(
        NEW.assessment_id, NEW.subject_id, NEW.subject_version_id, NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.assessment_id, OLD.subject_id, OLD.subject_version_id, OLD.created_at
    ) THEN
        RAISE EXCEPTION 'SUBJECT_REVIEW_BINDING_IMMUTABLE';
    END IF;
    IF OLD.status <> 'pending' THEN
        RAISE EXCEPTION 'SUBJECT_REVIEW_TERMINAL';
    END IF;
    IF NEW.status NOT IN ('approved', 'rejected', 'superseded') THEN
        RAISE EXCEPTION 'SUBJECT_REVIEW_STATE_CONFLICT';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'SUBJECT_REVIEW_VERSION_CONFLICT';
    END IF;
    IF NEW.status = 'rejected' AND btrim(NEW.reason) = '' THEN
        RAISE EXCEPTION 'SUBJECT_REVIEW_REASON_REQUIRED';
    END IF;
    IF NEW.status IN ('approved', 'rejected')
       AND (NEW.reviewed_by_id IS NULL OR NEW.reviewed_at IS NULL) THEN
        RAISE EXCEPTION 'SUBJECT_REVIEW_DECISION_INCOMPLETE';
    END IF;
    IF NEW.status = 'superseded'
       AND (NEW.reviewed_by_id IS NOT NULL OR NEW.reviewed_at IS NOT NULL) THEN
        RAISE EXCEPTION 'SUBJECT_REVIEW_SUPERSEDE_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_assert_risk_assessment() RETURNS trigger AS $$
DECLARE
    v_version_subject uuid;
    v_semantic_digest varchar(64);
    v_review_subject uuid;
    v_review_version uuid;
BEGIN
    SELECT subject_id, semantic_digest
      INTO v_version_subject, v_semantic_digest
      FROM subject_versions
     WHERE id = NEW.subject_version_id;
    IF NOT FOUND OR v_semantic_digest <> NEW.semantic_digest THEN
        RAISE EXCEPTION 'SUBJECT_RISK_ASSESSMENT_BINDING_INVALID';
    END IF;
    SELECT subject_id, subject_version_id
      INTO v_review_subject, v_review_version
      FROM subject_reviews
     WHERE assessment_id = NEW.id;
    IF FOUND AND (
        v_review_subject <> v_version_subject OR
        v_review_version <> NEW.subject_version_id
    ) THEN
        RAISE EXCEPTION 'SUBJECT_REVIEW_BINDING_INVALID';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_assert_review_binding() RETURNS trigger AS $$
DECLARE
    v_assessment_version uuid;
    v_version_subject uuid;
BEGIN
    SELECT subject_version_id
      INTO v_assessment_version
      FROM subject_risk_assessments
     WHERE id = NEW.assessment_id;
    SELECT subject_id
      INTO v_version_subject
      FROM subject_versions
     WHERE id = NEW.subject_version_id;
    IF NOT FOUND OR v_assessment_version <> NEW.subject_version_id
       OR v_version_subject <> NEW.subject_id THEN
        RAISE EXCEPTION 'SUBJECT_REVIEW_BINDING_INVALID';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_assert_catalog_revision() RETURNS trigger AS $$
DECLARE
    v_action_key varchar(100);
    v_status varchar(32);
BEGIN
    IF NEW.approval_request_id IS NULL THEN
        RAISE EXCEPTION 'SUBJECT_RISK_PUBLISH_APPROVAL_REQUIRED';
    END IF;
    SELECT action_key, status
      INTO v_action_key, v_status
      FROM approval_requests
     WHERE id = NEW.approval_request_id;
    IF NOT FOUND OR v_action_key <> 'subject_risk.catalog.publish'
       OR v_status <> 'executed' THEN
        RAISE EXCEPTION 'SUBJECT_RISK_PUBLISH_APPROVAL_INVALID';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS subjects_risk_revision_guard ON subject_risk_catalog_revisions;
CREATE TRIGGER subjects_risk_revision_guard
BEFORE UPDATE OR DELETE ON subject_risk_catalog_revisions
FOR EACH ROW EXECUTE FUNCTION subjects_guard_risk_evidence();

DROP TRIGGER IF EXISTS subjects_risk_assessment_guard ON subject_risk_assessments;
CREATE TRIGGER subjects_risk_assessment_guard
BEFORE UPDATE OR DELETE ON subject_risk_assessments
FOR EACH ROW EXECUTE FUNCTION subjects_guard_risk_evidence();

DROP TRIGGER IF EXISTS subjects_risk_hit_guard ON subject_risk_hits;
CREATE TRIGGER subjects_risk_hit_guard
BEFORE UPDATE OR DELETE ON subject_risk_hits
FOR EACH ROW EXECUTE FUNCTION subjects_guard_risk_evidence();

DROP TRIGGER IF EXISTS subjects_review_event_guard ON subject_review_events;
CREATE TRIGGER subjects_review_event_guard
BEFORE UPDATE OR DELETE ON subject_review_events
FOR EACH ROW EXECUTE FUNCTION subjects_guard_risk_evidence();

DROP TRIGGER IF EXISTS subjects_risk_type_guard ON subject_risk_types;
CREATE TRIGGER subjects_risk_type_guard
BEFORE UPDATE OR DELETE ON subject_risk_types
FOR EACH ROW EXECUTE FUNCTION subjects_guard_risk_draft();

DROP TRIGGER IF EXISTS subjects_risk_rule_guard ON subject_risk_rules;
CREATE TRIGGER subjects_risk_rule_guard
BEFORE UPDATE OR DELETE ON subject_risk_rules
FOR EACH ROW EXECUTE FUNCTION subjects_guard_risk_draft();

DROP TRIGGER IF EXISTS subjects_review_guard ON subject_reviews;
CREATE TRIGGER subjects_review_guard
BEFORE UPDATE OR DELETE ON subject_reviews
FOR EACH ROW EXECUTE FUNCTION subjects_guard_review();

DROP TRIGGER IF EXISTS subjects_risk_assessment_binding ON subject_risk_assessments;
CREATE CONSTRAINT TRIGGER subjects_risk_assessment_binding
AFTER INSERT ON subject_risk_assessments
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION subjects_assert_risk_assessment();

DROP TRIGGER IF EXISTS subjects_review_binding ON subject_reviews;
CREATE CONSTRAINT TRIGGER subjects_review_binding
AFTER INSERT ON subject_reviews
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION subjects_assert_review_binding();

DROP TRIGGER IF EXISTS subjects_catalog_revision_approval ON subject_risk_catalog_revisions;
CREATE CONSTRAINT TRIGGER subjects_catalog_revision_approval
AFTER INSERT ON subject_risk_catalog_revisions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION subjects_assert_catalog_revision();
"""

REMOVE_SQL = r"""
DROP TRIGGER IF EXISTS subjects_catalog_revision_approval ON subject_risk_catalog_revisions;
DROP TRIGGER IF EXISTS subjects_review_binding ON subject_reviews;
DROP TRIGGER IF EXISTS subjects_risk_assessment_binding ON subject_risk_assessments;
DROP TRIGGER IF EXISTS subjects_review_guard ON subject_reviews;
DROP TRIGGER IF EXISTS subjects_risk_rule_guard ON subject_risk_rules;
DROP TRIGGER IF EXISTS subjects_risk_type_guard ON subject_risk_types;
DROP TRIGGER IF EXISTS subjects_review_event_guard ON subject_review_events;
DROP TRIGGER IF EXISTS subjects_risk_hit_guard ON subject_risk_hits;
DROP TRIGGER IF EXISTS subjects_risk_assessment_guard ON subject_risk_assessments;
DROP TRIGGER IF EXISTS subjects_risk_revision_guard ON subject_risk_catalog_revisions;
DROP FUNCTION IF EXISTS subjects_assert_catalog_revision();
DROP FUNCTION IF EXISTS subjects_assert_review_binding();
DROP FUNCTION IF EXISTS subjects_assert_risk_assessment();
DROP FUNCTION IF EXISTS subjects_guard_review();
DROP FUNCTION IF EXISTS subjects_guard_risk_draft();
DROP FUNCTION IF EXISTS subjects_guard_risk_evidence();
"""


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(INSTALL_SQL)


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REMOVE_SQL)


class Migration(migrations.Migration):
    dependencies = [("subjects", "0008_subjectreview_subjectreviewevent_and_more")]
    operations = [migrations.RunPython(install_guards, remove_guards)]
