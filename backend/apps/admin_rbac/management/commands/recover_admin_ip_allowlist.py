from uuid import UUID, uuid4

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F

from apps.admin_rbac.models import (
    AdminRole,
    AdminSecurityEvent,
    SuperuserSecurityPolicy,
)
from apps.users.models import User


class Command(BaseCommand):
    help = "紧急关闭指定角色或超级管理员的 IP 白名单；不绕过高风险短信 Step-Up。"

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument("--role-id")
        target.add_argument("--superuser-id")
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        role_id = options.get("role_id")
        superuser_id = options.get("superuser_id")
        dry_run = options["dry_run"]
        if role_id:
            try:
                role = AdminRole.objects.select_for_update().get(pk=UUID(role_id))
            except (ValueError, AdminRole.DoesNotExist) as exc:
                raise CommandError("未找到指定角色。") from exc
            changed = role.ip_allowlist_enabled
            if changed and not dry_run:
                role.ip_allowlist_enabled = False
                role.security_version += 1
                role.save(update_fields=["ip_allowlist_enabled", "security_version", "updated_at"])
                User.objects.filter(admin_profile__role=role).update(
                    session_version=F("session_version") + 1
                )
                AdminSecurityEvent.objects.create(
                    event_type="emergency_recovery_used",
                    request_id=uuid4(),
                    role_version=role.version,
                    role_security_version=role.security_version,
                    stable_failure_reason="role_ip_allowlist_disabled",
                )
        else:
            try:
                policy = (
                    SuperuserSecurityPolicy.objects.select_for_update()
                    .select_related("user")
                    .get(user_id=UUID(superuser_id), user__is_superuser=True)
                )
            except (ValueError, SuperuserSecurityPolicy.DoesNotExist) as exc:
                raise CommandError("未找到指定超级管理员安全策略。") from exc
            changed = policy.ip_allowlist_enabled
            if changed and not dry_run:
                policy.ip_allowlist_enabled = False
                policy.security_version += 1
                policy.save(
                    update_fields=["ip_allowlist_enabled", "security_version", "updated_at"]
                )
                User.objects.filter(pk=policy.user_id).update(
                    session_version=F("session_version") + 1
                )
                AdminSecurityEvent.objects.create(
                    subject=policy.user,
                    event_type="emergency_recovery_used",
                    request_id=uuid4(),
                    policy_version=policy.security_version,
                    stable_failure_reason="superuser_ip_allowlist_disabled",
                )
        action = "将关闭" if dry_run and changed else "已关闭" if changed else "无需变更"
        self.stdout.write(f"紧急恢复检查完成：{action} IP 白名单。")
