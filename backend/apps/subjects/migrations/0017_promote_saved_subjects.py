from django.db import migrations


def promote_saved_subjects(apps, schema_editor):
    Subject = apps.get_model("subjects", "Subject")
    SubjectContext = apps.get_model("subjects", "SubjectContext")

    Subject.objects.filter(status="draft", current_version__isnull=False).update(status="active")

    invalid_contexts = SubjectContext.objects.filter(current_subject__isnull=False).exclude(
        current_subject__status="active",
        current_subject__current_version__isnull=False,
    )
    for context in invalid_contexts.iterator():
        replacement = (
            Subject.objects.filter(
                user_id=context.user_id,
                status="active",
                current_version__isnull=False,
            )
            .order_by("-updated_at", "id")
            .first()
        )
        context.current_subject_id = replacement.pk if replacement is not None else None
        context.version += 1
        context.save(update_fields=["current_subject", "version", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("subjects", "0016_subject_business_profile")]

    operations = [
        migrations.RunPython(promote_saved_subjects, migrations.RunPython.noop),
    ]
