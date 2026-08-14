from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION keywords_keyword_set_guard() RETURNS trigger AS $$
DECLARE
    v_subject_user uuid;
    v_subject_version_subject uuid;
    v_current_set uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'KEYWORD_SET_DELETE_FORBIDDEN';
    END IF;
    IF TG_OP = 'UPDATE' AND (OLD.user_id <> NEW.user_id OR OLD.subject_id <> NEW.subject_id) THEN
        RAISE EXCEPTION 'KEYWORD_SET_BINDING_IMMUTABLE';
    END IF;
    SELECT user_id INTO v_subject_user FROM subjects WHERE id = NEW.subject_id;
    IF v_subject_user IS NULL OR v_subject_user <> NEW.user_id THEN
        RAISE EXCEPTION 'KEYWORD_SET_OWNER_INVALID';
    END IF;
    IF NEW.draft_subject_version_id IS NOT NULL THEN
        SELECT subject_id INTO v_subject_version_subject
          FROM subject_versions WHERE id = NEW.draft_subject_version_id;
        IF v_subject_version_subject IS NULL OR v_subject_version_subject <> NEW.subject_id THEN
            RAISE EXCEPTION 'KEYWORD_DRAFT_SUBJECT_VERSION_INVALID';
        END IF;
    END IF;
    IF NEW.current_version_id IS NOT NULL THEN
        SELECT keyword_set_id INTO v_current_set
          FROM keyword_set_versions WHERE id = NEW.current_version_id;
        IF v_current_set IS NULL OR v_current_set <> NEW.id THEN
            RAISE EXCEPTION 'KEYWORD_CURRENT_VERSION_INVALID';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS keywords_keyword_set_guard_trg ON keyword_sets;
CREATE TRIGGER keywords_keyword_set_guard_trg
BEFORE INSERT OR UPDATE OR DELETE ON keyword_sets
FOR EACH ROW EXECUTE FUNCTION keywords_keyword_set_guard();

CREATE OR REPLACE FUNCTION keywords_keyword_version_guard() RETURNS trigger AS $$
DECLARE
    v_set record;
    v_subject_version_subject uuid;
    v_subject_current_version uuid;
    v_max bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'KEYWORD_VERSION_IMMUTABLE';
    END IF;
    SELECT user_id, subject_id INTO v_set FROM keyword_sets WHERE id = NEW.keyword_set_id;
    IF NOT FOUND OR v_set.user_id <> NEW.user_id OR v_set.subject_id <> NEW.subject_id THEN
        RAISE EXCEPTION 'KEYWORD_VERSION_OWNER_INVALID';
    END IF;
    IF NEW.created_by_id IS NOT NULL AND NEW.created_by_id <> NEW.user_id THEN
        RAISE EXCEPTION 'KEYWORD_VERSION_CREATOR_INVALID';
    END IF;
    SELECT subject_id INTO v_subject_version_subject
      FROM subject_versions WHERE id = NEW.subject_version_id;
    IF v_subject_version_subject IS NULL OR v_subject_version_subject <> NEW.subject_id THEN
        RAISE EXCEPTION 'KEYWORD_VERSION_SUBJECT_VERSION_INVALID';
    END IF;
    SELECT current_version_id INTO v_subject_current_version
      FROM subjects WHERE id = NEW.subject_id;
    IF v_subject_current_version IS NULL OR v_subject_current_version <> NEW.subject_version_id THEN
        RAISE EXCEPTION 'KEYWORD_VERSION_SUBJECT_VERSION_STALE';
    END IF;
    SELECT MAX(version_no) INTO v_max
      FROM keyword_set_versions WHERE keyword_set_id = NEW.keyword_set_id;
    IF NEW.version_no <> COALESCE(v_max, 0) + 1 THEN
        RAISE EXCEPTION 'KEYWORD_VERSION_SEQUENCE_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS keywords_keyword_version_guard_trg ON keyword_set_versions;
CREATE TRIGGER keywords_keyword_version_guard_trg
BEFORE INSERT OR UPDATE OR DELETE ON keyword_set_versions
FOR EACH ROW EXECUTE FUNCTION keywords_keyword_version_guard();

CREATE OR REPLACE FUNCTION keywords_keyword_guard() RETURNS trigger AS $$
DECLARE
    v_current uuid;
    v_target_no bigint;
    v_max_no bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'KEYWORD_FORMAL_IMMUTABLE';
    END IF;
    SELECT ks.current_version_id, kv.version_no
      INTO v_current, v_target_no
      FROM keyword_set_versions kv
      JOIN keyword_sets ks ON ks.id = kv.keyword_set_id
     WHERE kv.id = NEW.keyword_set_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'KEYWORD_VERSION_MISSING';
    END IF;
    SELECT MAX(version_no) INTO v_max_no
      FROM keyword_set_versions
     WHERE keyword_set_id = (
         SELECT keyword_set_id FROM keyword_set_versions WHERE id = NEW.keyword_set_version_id
     );
    IF v_current = NEW.keyword_set_version_id OR v_target_no <> v_max_no THEN
        RAISE EXCEPTION 'KEYWORD_FINALIZED_VERSION_APPEND_FORBIDDEN';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS keywords_keyword_guard_trg ON keywords;
CREATE TRIGGER keywords_keyword_guard_trg
BEFORE INSERT OR UPDATE OR DELETE ON keywords
FOR EACH ROW EXECUTE FUNCTION keywords_keyword_guard();

CREATE OR REPLACE FUNCTION keywords_assert_set(p_set uuid) RETURNS void AS $$
DECLARE
    v_set record;
    v_max bigint;
    v_current record;
    v_count integer;
    v_min integer;
    v_max_pos integer;
    v_distinct integer;
BEGIN
    SELECT current_version_id INTO v_set FROM keyword_sets WHERE id = p_set;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    SELECT MAX(version_no) INTO v_max FROM keyword_set_versions WHERE keyword_set_id = p_set;
    IF v_max IS NULL THEN
        IF v_set.current_version_id IS NOT NULL THEN
            RAISE EXCEPTION 'KEYWORD_CURRENT_VERSION_WITHOUT_HISTORY';
        END IF;
        RETURN;
    END IF;
    IF v_set.current_version_id IS NULL THEN
        RAISE EXCEPTION 'KEYWORD_CURRENT_VERSION_REQUIRED';
    END IF;
    SELECT id, keyword_set_id, version_no, item_count INTO v_current
      FROM keyword_set_versions WHERE id = v_set.current_version_id;
    IF NOT FOUND OR v_current.keyword_set_id <> p_set OR v_current.version_no <> v_max THEN
        RAISE EXCEPTION 'KEYWORD_CURRENT_VERSION_NOT_MAX';
    END IF;
    SELECT COUNT(*), MIN(sort_order), MAX(sort_order), COUNT(DISTINCT sort_order)
      INTO v_count, v_min, v_max_pos, v_distinct
      FROM keywords WHERE keyword_set_version_id = v_current.id;
    IF v_count <> v_current.item_count OR v_count < 1
       OR v_min <> 0 OR v_max_pos <> v_count - 1 OR v_distinct <> v_count THEN
        RAISE EXCEPTION 'KEYWORD_FORMAL_POSITIONS_INVALID';
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION keywords_assert_set_from_set() RETURNS trigger AS $$
BEGIN
    PERFORM keywords_assert_set(NEW.id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION keywords_assert_set_from_version() RETURNS trigger AS $$
BEGIN
    PERFORM keywords_assert_set(NEW.keyword_set_id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION keywords_assert_set_from_keyword() RETURNS trigger AS $$
DECLARE
    v_set uuid;
BEGIN
    SELECT keyword_set_id INTO v_set
      FROM keyword_set_versions WHERE id = NEW.keyword_set_version_id;
    PERFORM keywords_assert_set(v_set);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS keywords_set_consistency_trg ON keyword_sets;
CREATE CONSTRAINT TRIGGER keywords_set_consistency_trg
AFTER INSERT OR UPDATE ON keyword_sets
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION keywords_assert_set_from_set();

DROP TRIGGER IF EXISTS keywords_version_consistency_trg ON keyword_set_versions;
CREATE CONSTRAINT TRIGGER keywords_version_consistency_trg
AFTER INSERT ON keyword_set_versions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION keywords_assert_set_from_version();

DROP TRIGGER IF EXISTS keywords_item_consistency_trg ON keywords;
CREATE CONSTRAINT TRIGGER keywords_item_consistency_trg
AFTER INSERT ON keywords
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION keywords_assert_set_from_keyword();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS keywords_item_consistency_trg ON keywords;
DROP TRIGGER IF EXISTS keywords_version_consistency_trg ON keyword_set_versions;
DROP TRIGGER IF EXISTS keywords_set_consistency_trg ON keyword_sets;
DROP TRIGGER IF EXISTS keywords_keyword_guard_trg ON keywords;
DROP TRIGGER IF EXISTS keywords_keyword_version_guard_trg ON keyword_set_versions;
DROP TRIGGER IF EXISTS keywords_keyword_set_guard_trg ON keyword_sets;
DROP FUNCTION IF EXISTS keywords_assert_set_from_keyword();
DROP FUNCTION IF EXISTS keywords_assert_set_from_version();
DROP FUNCTION IF EXISTS keywords_assert_set_from_set();
DROP FUNCTION IF EXISTS keywords_assert_set(uuid);
DROP FUNCTION IF EXISTS keywords_keyword_guard();
DROP FUNCTION IF EXISTS keywords_keyword_version_guard();
DROP FUNCTION IF EXISTS keywords_keyword_set_guard();
"""


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD_SQL)


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("keywords", "0001_initial")]
    operations = [migrations.RunPython(install_guards, remove_guards)]
