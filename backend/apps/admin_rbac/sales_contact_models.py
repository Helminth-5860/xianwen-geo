import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class SalesContactConfiguration(models.Model):  # noqa: DJ008
    class Scope(models.TextChoices):
        GLOBAL = "global", "平台全局"
        AGENT = "agent", "代理"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=16, choices=Scope.choices)
    owner_admin = models.OneToOneField(
        "admin_rbac.AdminProfile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sales_contact_configuration",
    )
    object_key = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=64, blank=True)
    size_bytes = models.PositiveIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    enabled = models.BooleanField(default=False)
    version = models.PositiveBigIntegerField(default=1)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_sales_contact_configurations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sales_contact_configurations"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(scope="global", owner_admin__isnull=True)
                    | Q(scope="agent", owner_admin__isnull=False)
                ),
                name="sales_contact_scope_owner_valid",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1),
                name="sales_contact_version_gte_1",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        object_key="",
                        mime_type="",
                        size_bytes__isnull=True,
                        sha256="",
                        enabled=False,
                    )
                    | (
                        ~Q(object_key="")
                        & ~Q(mime_type="")
                        & Q(size_bytes__gt=0)
                        & ~Q(sha256="")
                    )
                ),
                name="sales_contact_media_state_valid",
            ),
            models.UniqueConstraint(
                fields=("scope",),
                condition=Q(scope="global"),
                name="sales_contact_single_global",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.scope == self.Scope.GLOBAL and self.owner_admin_id is not None:
            errors["owner_admin"] = "平台全局配置不能绑定代理。"
        if self.scope == self.Scope.AGENT:
            owner = self.owner_admin
            if owner is None or owner.user.is_superuser or owner.role_id is None:
                errors["owner_admin"] = "代理配置必须绑定有效的普通管理员。"
        if self.enabled and not self.object_key:
            errors["enabled"] = "请先上传销售微信二维码。"
        if errors:
            raise ValidationError(errors)
