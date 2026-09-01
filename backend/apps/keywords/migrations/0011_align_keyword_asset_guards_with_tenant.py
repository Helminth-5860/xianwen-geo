from django.db import migrations


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION keywords_keyword_set_guard() RETURNS trigger AS $$
DECLARE
    v_subject_user uuid;
    v_subject_tenant uuid;
    v_user_tenant uuid;
    v_subject_version_subject uuid;
    v_current_set uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'KEYWORD_SET_DELETE_FORBIDDEN';
    END IF;
    IF TG_OP = 'UPDATE' AND (OLD.user_id <> NEW.user_id OR OLD.subject_id <> NEW.subject_id) THEN
        RAISE EXCEPTION 'KEYWORD_SET_BINDING_IMMUTABLE';
    END IF;
    SELECT user_id, tenant_id
      INTO v_subject_user, v_subject_tenant
      FROM subjects WHERE id = NEW.subject_id;
    SELECT tenant_id INTO v_user_tenant FROM users WHERE id = NEW.user_id;
    IF v_subject_user IS NULL
       OR (
           v_subject_tenant IS NULL
           AND v_subject_user <> NEW.user_id
       )
       OR (
           v_subject_tenant IS NOT NULL
           AND (v_user_tenant IS NULL OR v_user_tenant <> v_subject_tenant)
       ) THEN
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

CREATE OR REPLACE FUNCTION keywords_keyword_version_guard() RETURNS trigger AS $$
DECLARE
    v_set_subject uuid;
    v_subject_user uuid;
    v_subject_tenant uuid;
    v_user_tenant uuid;
    v_subject_version_subject uuid;
    v_subject_current_version uuid;
    v_max bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'KEYWORD_VERSION_IMMUTABLE';
    END IF;
    SELECT subject_id INTO v_set_subject
      FROM keyword_sets WHERE id = NEW.keyword_set_id;
    IF NOT FOUND OR v_set_subject <> NEW.subject_id THEN
        RAISE EXCEPTION 'KEYWORD_VERSION_OWNER_INVALID';
    END IF;
    SELECT user_id, tenant_id
      INTO v_subject_user, v_subject_tenant
      FROM subjects WHERE id = NEW.subject_id;
    SELECT tenant_id INTO v_user_tenant FROM users WHERE id = NEW.user_id;
    IF v_subject_user IS NULL
       OR (
           v_subject_tenant IS NULL
           AND v_subject_user <> NEW.user_id
       )
       OR (
           v_subject_tenant IS NOT NULL
           AND (v_user_tenant IS NULL OR v_user_tenant <> v_subject_tenant)
       ) THEN
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
"""


REVERSE_SQL = r"""
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
"""


class Migration(migrations.Migration):
    dependencies = [("keywords", "0010_align_generation_guard_with_tenant_and_item_quota")]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
