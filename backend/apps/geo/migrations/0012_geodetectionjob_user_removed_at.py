from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("geo", "0011_stage2_share_postgresql_guards")]

    operations = [
        migrations.AddField(
            model_name="geodetectionjob",
            name="user_removed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="geodetectionjob",
            index=models.Index(
                fields=["user", "subject", "user_removed_at", "created_at"],
                name="geo_job_user_sub_rm_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="geodetectionjob",
            constraint=models.CheckConstraint(
                condition=Q(user_removed_at__isnull=True)
                | Q(status__in=("partial", "succeeded", "failed", "cancelled")),
                name="geo_job_removed_terminal",
            ),
        ),
    ]
