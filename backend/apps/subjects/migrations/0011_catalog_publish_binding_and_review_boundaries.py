from django.db import migrations, models


def reject_existing_revisions(apps, schema_editor):
    Revision = apps.get_model("subjects", "SubjectRiskCatalogRevision")
    if Revision.objects.exists():
        raise RuntimeError(
            "Existing SubjectRiskCatalogRevision rows require an audited forward data migration; "
            "draft_version and approval digest evidence will not be guessed."
        )


INSTALL_SQL = r"""
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
    IF NEW.status = 'rejected' AND btrim(NEW.public_reason) = '' THEN
        RAISE EXCEPTION 'SUBJECT_REVIEW_REASON_REQUIRED';
    END IF;
    IF NEW.status IN ('approved', 'rejected')
       AND (NEW.reviewed_by_id IS NULL OR NEW.reviewed_at IS NULL) THEN
        RAISE EXCEPTION 'SUBJECT_REVIEW_DECISION_INCOMPLETE';
    END IF;
    IF NEW.status = 'superseded'
       AND (
           NEW.reviewed_by_id IS NOT NULL OR NEW.reviewed_at IS NOT NULL OR
           btrim(NEW.public_reason) <> '' OR btrim(NEW.internal_note) <> ''
       ) THEN
        RAISE EXCEPTION 'SUBJECT_REVIEW_SUPERSEDE_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_assert_catalog_revision() RETURNS trigger AS $$
DECLARE
    v_action_key varchar(100);
    v_status varchar(32);
    v_target_version bigint;
    v_draft_digest text;
BEGIN
    IF NEW.approval_request_id IS NULL THEN
        RAISE EXCEPTION 'SUBJECT_RISK_PUBLISH_APPROVAL_REQUIRED';
    END IF;
    SELECT action_key, status, target_version, sanitized_payload->>'draft_digest'
      INTO v_action_key, v_status, v_target_version, v_draft_digest
      FROM approval_requests
     WHERE id = NEW.approval_request_id;
    IF NOT FOUND OR v_action_key <> 'subject_risk.catalog.publish'
       OR v_status <> 'executed'
       OR v_target_version <> NEW.draft_version
       OR v_draft_digest IS DISTINCT FROM NEW.snapshot_digest THEN
        RAISE EXCEPTION 'SUBJECT_RISK_PUBLISH_APPROVAL_INVALID';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(INSTALL_SQL)


class Migration(migrations.Migration):
    dependencies = [("subjects", "0010_initialize_subject_risk_state")]

    operations = [
        migrations.AddField(
            model_name="subjectriskcatalogrevision",
            name="draft_version",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(reject_existing_revisions, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="subjectriskcatalogrevision",
            name="draft_version",
            field=models.PositiveBigIntegerField(),
        ),
        migrations.AddConstraint(
            model_name="subjectriskcatalogrevision",
            constraint=models.CheckConstraint(
                condition=models.Q(draft_version__gte=1),
                name="subject_risk_revision_draft_version_gte_1",
            ),
        ),
        migrations.RenameField(
            model_name="subjectreview",
            old_name="reason",
            new_name="public_reason",
        ),
        migrations.AddField(
            model_name="subjectreview",
            name="internal_note",
            field=models.CharField(blank=True, default="", max_length=1000),
            preserve_default=False,
        ),
        migrations.RunPython(install_guards, migrations.RunPython.noop),
    ]