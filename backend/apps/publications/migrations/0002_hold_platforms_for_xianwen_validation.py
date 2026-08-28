from django.db import migrations


def hold_unvalidated_platforms(apps, schema_editor):
    Platform = apps.get_model("publications", "PublicationPlatform")
    Platform.objects.exclude(channel__key="sohu").update(validation_status="testing")
    Platform.objects.filter(channel__key="sohu").update(validation_status="paused")


class Migration(migrations.Migration):
    dependencies = [("publications", "0001_initial")]
    operations = [migrations.RunPython(hold_unvalidated_platforms, migrations.RunPython.noop)]
