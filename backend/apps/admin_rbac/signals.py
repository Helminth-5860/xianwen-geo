from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.users.models import User

from .models import AdminProfile, SuperuserSecurityPolicy


@receiver(post_save, sender=User)
def ensure_superuser_profile(sender, instance: User, created: bool, **kwargs) -> None:
    if created and instance.is_superuser:
        AdminProfile.objects.get_or_create(
            user=instance,
            defaults={"admin_status": AdminProfile.Status.ACTIVE, "role": None},
        )
        SuperuserSecurityPolicy.objects.get_or_create(user=instance)
