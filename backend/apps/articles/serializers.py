from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer


class SourcePackCreateSerializer(StrictSerializer):
    subject_id = serializers.UUIDField()
    article_type_id = serializers.UUIDField()
    document_source_ids = serializers.ListField(
        child=serializers.UUIDField(), default=list, max_length=50
    )
    web_source_ids = serializers.ListField(
        child=serializers.UUIDField(), default=list, max_length=50
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        for key in ("document_source_ids", "web_source_ids"):
            if len(attrs[key]) != len(set(attrs[key])):
                raise serializers.ValidationError(f"{key} must be unique")
        return attrs


class ConflictResolutionSerializer(StrictSerializer):
    key = serializers.CharField(max_length=100)
    value = serializers.CharField(max_length=500)


class SourcePackConfirmSerializer(StrictSerializer):
    selected_item_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, max_length=101
    )
    conflict_resolutions = ConflictResolutionSerializer(many=True, default=list)


class ArticleCreateSerializer(StrictSerializer):
    article_type_id = serializers.UUIDField(required=False, allow_null=True)
    custom_type = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )
    content_depth = serializers.ChoiceField(
        choices=("concise", "standard", "deep"), default="standard"
    )
    title = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    source_pack_id = serializers.UUIDField(required=False, allow_null=True)


class ArticleDraftSerializer(StrictSerializer):
    title = serializers.CharField(max_length=500, allow_blank=True)
    content = serializers.CharField(max_length=200_000, allow_blank=True, trim_whitespace=False)
    content_depth = serializers.ChoiceField(choices=("concise", "standard", "deep"))
    expected_version = serializers.IntegerField(min_value=1)


class OutlineWriteSerializer(StrictSerializer):
    text = serializers.CharField(max_length=30_000, trim_whitespace=False)
    expected_version = serializers.IntegerField(min_value=1)
    confirm = serializers.BooleanField(default=False)


class OptimizationSerializer(StrictSerializer):
    instruction = serializers.CharField(max_length=2000)
    selection = serializers.CharField(
        max_length=20_000, required=False, allow_blank=True, default=""
    )


class ComparisonChoiceSerializer(StrictSerializer):
    choice = serializers.ChoiceField(choices=("original", "optimized"))


class ChannelBatchSerializer(StrictSerializer):
    channel_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, max_length=20
    )

    def validate_channel_ids(self, values):
        if len(values) != len(set(values)):
            raise serializers.ValidationError("channel_ids must be unique")
        return values


class AdaptationWriteSerializer(StrictSerializer):
    title = serializers.CharField(max_length=500)
    content = serializers.CharField(max_length=200_000, trim_whitespace=False)
    expected_version = serializers.IntegerField(min_value=1)


class PublicationCheckSerializer(StrictSerializer):
    subject_id = serializers.UUIDField()
    article_id = serializers.UUIDField(required=False, allow_null=True)
    adaptation_id = serializers.UUIDField(required=False, allow_null=True)
    channel_id = serializers.UUIDField()
    url = serializers.URLField(max_length=4096)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if (attrs.get("article_id") is None) == (attrs.get("adaptation_id") is None):
            raise serializers.ValidationError("exactly one article_id or adaptation_id is required")
        return attrs


class ArticleExportSerializer(StrictSerializer):
    format = serializers.ChoiceField(choices=("word", "pdf", "txt", "markdown", "html"))
