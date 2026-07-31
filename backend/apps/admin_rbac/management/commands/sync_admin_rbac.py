from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from apps.users.models import User

from ...catalog import PERMISSION_CATALOG
from ...models import AdminPermission, AdminProfile


class Command(BaseCommand):
    help = "检查或幂等修复 RBAC 权限目录与管理员资料不变量。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="实际写入；默认 dry-run。")

    @transaction.atomic
    def handle(self, *args, **options):
        apply_changes = options["apply"]
        catalog_keys = {item.key for item in PERMISSION_CATALOG}
        extra_keys = list(
            AdminPermission.objects.exclude(key__in=catalog_keys).values_list("key", flat=True)
        )
        changes = len(extra_keys)
        for item in PERMISSION_CATALOG:
            current = AdminPermission.objects.filter(key=item.key).first()
            expected = {
                "name": item.name,
                "module": item.module,
                "permission_type": item.permission_type,
                "status": AdminPermission.Status.ACTIVE,
                "sort_order": item.sort_order,
                "superuser_only": item.superuser_only,
            }
            if current is None or any(
                getattr(current, key) != value for key, value in expected.items()
            ):
                changes += 1
                if apply_changes:
                    AdminPermission.objects.update_or_create(key=item.key, defaults=expected)
        for user in User.objects.filter(
            Q(is_staff=True) | Q(is_superuser=True), admin_profile__isnull=True
        ):
            changes += 1
            if apply_changes:
                AdminProfile.objects.create(
                    user=user,
                    admin_status=(
                        AdminProfile.Status.ACTIVE
                        if user.is_superuser
                        else AdminProfile.Status.DISABLED
                    ),
                )
                if not user.is_superuser:
                    user.is_staff = False
                    user.session_version += 1
                    user.save(update_fields=["is_staff", "session_version", "updated_at"])
        if extra_keys:
            self.stdout.write(
                self.style.WARNING(
                    f"catalog drift：发现 {len(extra_keys)} 个非目录权限；不会自动删除。"
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"{'已应用' if apply_changes else 'dry-run'}：发现 {changes} 项需要同步。"
            )
        )
        if not apply_changes:
            transaction.set_rollback(True)
