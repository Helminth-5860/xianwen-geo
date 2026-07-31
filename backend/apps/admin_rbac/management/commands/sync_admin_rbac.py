from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from apps.users.models import User

from ...catalog import PERMISSION_CATALOG
from ...models import AdminPermission, AdminProfile
from ...services import set_permission_status


class Command(BaseCommand):
    help = "检查或幂等修复 RBAC 权限目录与管理员资料不变量。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="实际写入；默认 dry-run。")
        parser.add_argument("--permission-key")
        parser.add_argument(
            "--permission-status",
            choices=AdminPermission.Status.values,
            help="通过受控服务修改目录权限状态；必须与 --apply 同时使用。",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        apply_changes = options["apply"]
        permission_key = options["permission_key"]
        permission_status = options["permission_status"]
        if bool(permission_key) != bool(permission_status):
            raise CommandError("--permission-key 与 --permission-status 必须同时提供。")
        if permission_key and not apply_changes:
            raise CommandError("修改权限状态必须显式指定 --apply。")

        catalog_keys = {item.key for item in PERMISSION_CATALOG}
        if permission_key and permission_key not in catalog_keys:
            raise CommandError("只能修改 catalog 中已声明的权限。")

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
                "sort_order": item.sort_order,
                "superuser_only": item.superuser_only,
            }
            metadata_changed = current is None or any(
                getattr(current, key) != value for key, value in expected.items()
            )
            if metadata_changed:
                changes += 1
                if apply_changes:
                    if current is None:
                        current = AdminPermission.objects.create(
                            key=item.key,
                            status=AdminPermission.Status.ACTIVE,
                            **expected,
                        )
                    else:
                        for key, value in expected.items():
                            setattr(current, key, value)
                        current.save(update_fields=list(expected))

            if item.key == permission_key and current is not None:
                if current.status != permission_status:
                    changes += 1
                    if apply_changes:
                        set_permission_status(
                            permission_key=item.key,
                            status=permission_status,
                        )

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
