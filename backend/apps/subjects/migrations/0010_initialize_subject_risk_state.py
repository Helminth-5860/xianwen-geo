from django.db import migrations


def initialize_state(apps, schema_editor):
    State = apps.get_model("subjects", "SubjectRiskCatalogState")
    State.objects.get_or_create(pk=1, defaults={"version": 1})


class Migration(migrations.Migration):
    dependencies = [("subjects", "0009_subject_risk_postgresql_guards")]
    operations = [migrations.RunPython(initialize_state, migrations.RunPython.noop)]
