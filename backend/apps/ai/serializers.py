from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .models import AIModelRuntimeConfig, APICredential


class AIModelRuntimeConfigSerializer(serializers.ModelSerializer):
    model_id = serializers.UUIDField(source="model.id", read_only=True)
    model_key = serializers.CharField(source="model.model_key", read_only=True)
    provider_key = serializers.CharField(source="model.provider.provider_key", read_only=True)
    canonical_display_name = serializers.CharField(
        source="model.canonical_display_name", read_only=True
    )
    canonical_order = serializers.IntegerField(source="model.canonical_order", read_only=True)
    purpose = serializers.CharField(source="model.purpose", read_only=True)
    is_builtin = serializers.BooleanField(source="model.is_builtin", read_only=True)
    display_name = serializers.CharField(read_only=True)
    cost_unit = serializers.SerializerMethodField()

    class Meta:
        model = AIModelRuntimeConfig
        fields = (
            "model_id",
            "provider_key",
            "model_key",
            "canonical_display_name",
            "display_name",
            "display_name_override",
            "canonical_order",
            "purpose",
            "is_builtin",
            "provider_model_id",
            "api_version",
            "enabled",
            "sort_order",
            "network_access_enabled",
            "web_search_failure_policy",
            "timeout_seconds",
            "max_retries",
            "retry_base_seconds",
            "retry_backoff",
            "max_concurrency",
            "cost_unit",
            "currency",
            "input_cost",
            "output_cost",
            "request_cost",
            "paused",
            "pause_reason",
            "version",
            "created_at",
            "updated_at",
        )

    def get_cost_unit(self, obj):
        return obj.cost_unit or None


class AIModelRuntimeConfigUpdateSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    display_name_override = serializers.CharField(
        required=False, allow_blank=True, max_length=150, trim_whitespace=False
    )
    provider_model_id = serializers.CharField(
        required=False, allow_blank=True, max_length=255, trim_whitespace=False
    )
    api_version = serializers.CharField(
        required=False, allow_blank=True, max_length=100, trim_whitespace=False
    )
    sort_order = serializers.IntegerField(required=False, min_value=0, max_value=65535)
    network_access_enabled = serializers.BooleanField(required=False)
    web_search_failure_policy = serializers.ChoiceField(
        required=False, choices=AIModelRuntimeConfig.WebSearchFailurePolicy.values
    )
    timeout_seconds = serializers.IntegerField(required=False, min_value=1, max_value=300)
    max_retries = serializers.IntegerField(required=False, min_value=0, max_value=10)
    retry_base_seconds = serializers.IntegerField(required=False, min_value=1, max_value=3600)
    retry_backoff = serializers.ChoiceField(
        required=False, choices=AIModelRuntimeConfig.RetryBackoff.values
    )
    max_concurrency = serializers.IntegerField(required=False, min_value=1, max_value=1000)
    cost_unit = serializers.ChoiceField(
        required=False, allow_null=True, choices=AIModelRuntimeConfig.CostUnit.values
    )
    currency = serializers.ChoiceField(required=False, choices=("CNY",))
    input_cost = serializers.DecimalField(
        required=False, allow_null=True, min_value=0, max_digits=18, decimal_places=6
    )
    output_cost = serializers.DecimalField(
        required=False, allow_null=True, min_value=0, max_digits=18, decimal_places=6
    )
    request_cost = serializers.DecimalField(
        required=False, allow_null=True, min_value=0, max_digits=18, decimal_places=6
    )

    def validate(self, attrs):
        if set(attrs) == {"expected_version"}:
            raise serializers.ValidationError({"non_field_errors": ["必须提供修改字段。"]})
        return attrs


class ExpectedAIModelConfigVersionSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)


class PauseAIModelSerializer(ExpectedAIModelConfigVersionSerializer):
    reason = serializers.CharField(max_length=200, trim_whitespace=False)


class APICredentialSerializer(serializers.ModelSerializer):
    provider_key = serializers.CharField(source="provider.provider_key", read_only=True)
    provider_name = serializers.CharField(source="provider.canonical_name", read_only=True)
    secret_mask = serializers.CharField(read_only=True)

    class Meta:
        model = APICredential
        fields = (
            "id",
            "provider_key",
            "provider_name",
            "environment",
            "secret_mask",
            "version_no",
            "status",
            "created_at",
        )
        read_only_fields = fields


class APICredentialCreateSerializer(StrictSerializer):
    provider_key = serializers.CharField(max_length=100)
    environment = serializers.ChoiceField(choices=("staging", "production"))
    api_key = serializers.CharField(
        min_length=8, max_length=4096, trim_whitespace=False, write_only=True
    )


class APICredentialRotateSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    api_key = serializers.CharField(
        min_length=8, max_length=4096, trim_whitespace=False, write_only=True
    )


class APICredentialTestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
