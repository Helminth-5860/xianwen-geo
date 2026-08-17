from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from .catalog import BUILTIN_MODEL_KEYS, BUILTIN_PROVIDER_KEYS


class AIProvider(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider_key = models.CharField(max_length=100, unique=True)
    canonical_name = models.CharField(max_length=150)
    is_builtin = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_providers"
        ordering = ("provider_key", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(provider_key__in=BUILTIN_PROVIDER_KEYS),
                name="ai_provider_fixed_key",
            ),
            models.CheckConstraint(condition=models.Q(is_builtin=True), name="ai_provider_builtin"),
        ]


class AIModel(models.Model):  # noqa: DJ008
    class Purpose(models.TextChoices):
        GEO_DETECTION = "geo_detection", "GEO 检测"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(AIProvider, on_delete=models.PROTECT, related_name="models")
    model_key = models.CharField(max_length=100, unique=True)
    canonical_display_name = models.CharField(max_length=150)
    canonical_order = models.PositiveSmallIntegerField(unique=True)
    purpose = models.CharField(
        max_length=32, choices=Purpose.choices, default=Purpose.GEO_DETECTION
    )
    is_builtin = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_models"
        ordering = ("canonical_order", "model_key", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(model_key__in=BUILTIN_MODEL_KEYS), name="ai_model_fixed_key"
            ),
            models.CheckConstraint(condition=models.Q(is_builtin=True), name="ai_model_builtin"),
            models.CheckConstraint(
                condition=models.Q(purpose="geo_detection"), name="ai_model_detection_only"
            ),
            models.UniqueConstraint(
                fields=("provider", "model_key"), name="ai_model_provider_identity_unique"
            ),
        ]


class AIModelRuntimeConfig(models.Model):  # noqa: DJ008
    class WebSearchFailurePolicy(models.TextChoices):
        DEGRADE_FORMAL = "degrade_formal", "降级普通回答并参与正式评分"
        DEGRADE_REFERENCE = "degrade_reference", "降级普通回答仅作参考"
        FAIL = "fail", "直接失败"

    class RetryBackoff(models.TextChoices):
        FIXED = "fixed", "固定间隔"
        EXPONENTIAL = "exponential", "指数退避"

    class CostUnit(models.TextChoices):
        PER_MILLION_TOKENS = "per_million_tokens", "每百万 Token"
        PER_REQUEST = "per_request", "每次请求"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model = models.OneToOneField(AIModel, on_delete=models.PROTECT, related_name="runtime_config")
    display_name_override = models.CharField(max_length=150, blank=True)
    provider_model_id = models.CharField(max_length=255, blank=True)
    api_version = models.CharField(max_length=100, blank=True)
    enabled = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField()
    network_access_enabled = models.BooleanField(default=False)
    web_search_failure_policy = models.CharField(
        max_length=32,
        choices=WebSearchFailurePolicy.choices,
        default=WebSearchFailurePolicy.FAIL,
    )
    timeout_seconds = models.PositiveSmallIntegerField(default=30)
    max_retries = models.PositiveSmallIntegerField(default=2)
    retry_base_seconds = models.PositiveIntegerField(default=30)
    retry_backoff = models.CharField(
        max_length=16, choices=RetryBackoff.choices, default=RetryBackoff.EXPONENTIAL
    )
    max_concurrency = models.PositiveSmallIntegerField(default=1)
    cost_unit = models.CharField(max_length=32, choices=CostUnit.choices, blank=True)
    currency = models.CharField(max_length=3, default="CNY")
    input_cost = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    output_cost = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    request_cost = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    paused = models.BooleanField(default=False)
    pause_reason = models.CharField(max_length=200, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_ai_model_runtime_configs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_model_runtime_configs"
        ordering = ("sort_order", "model__model_key", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(timeout_seconds__gte=1, timeout_seconds__lte=300),
                name="ai_runtime_timeout_range",
            ),
            models.CheckConstraint(
                condition=models.Q(max_retries__gte=0, max_retries__lte=10),
                name="ai_runtime_retries_range",
            ),
            models.CheckConstraint(
                condition=models.Q(retry_base_seconds__gte=1, retry_base_seconds__lte=3600),
                name="ai_runtime_retry_base_range",
            ),
            models.CheckConstraint(
                condition=models.Q(max_concurrency__gte=1, max_concurrency__lte=1000),
                name="ai_runtime_concurrency_range",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="ai_runtime_version_gte_1"
            ),
            models.CheckConstraint(
                condition=models.Q(currency="CNY"), name="ai_runtime_currency_cny"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        cost_unit="",
                        input_cost__isnull=True,
                        output_cost__isnull=True,
                        request_cost__isnull=True,
                    )
                    | models.Q(
                        cost_unit="per_million_tokens",
                        input_cost__isnull=False,
                        output_cost__isnull=False,
                        request_cost__isnull=True,
                        input_cost__gte=0,
                        output_cost__gte=0,
                    )
                    | models.Q(
                        cost_unit="per_request",
                        input_cost__isnull=True,
                        output_cost__isnull=True,
                        request_cost__isnull=False,
                        request_cost__gte=0,
                    )
                ),
                name="ai_runtime_cost_shape",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(paused=False, pause_reason="")
                    | models.Q(paused=True) & ~models.Q(pause_reason="")
                ),
                name="ai_runtime_pause_reason",
            ),
        ]

    @property
    def display_name(self) -> str:
        return self.display_name_override or self.model.canonical_display_name
