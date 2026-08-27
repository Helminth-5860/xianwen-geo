from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer


class VideoScriptCreateSerializer(StrictSerializer):
    platform = serializers.ChoiceField(
        choices=("douyin", "wechat_channels", "xiaohongshu", "bilibili", "general")
    )
    video_type = serializers.ChoiceField(
        choices=("talking_head", "brand", "product", "knowledge", "case")
    )
    duration_seconds = serializers.IntegerField(min_value=10, max_value=180)
    style = serializers.ChoiceField(
        choices=("professional", "natural", "emotional", "conversion", "knowledge")
    )
    source_mode = serializers.ChoiceField(choices=("subject", "article", "custom"))
    topic = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    document_source_ids = serializers.ListField(
        child=serializers.UUIDField(), default=list, max_length=8
    )
    web_source_ids = serializers.ListField(
        child=serializers.UUIDField(), default=list, max_length=8
    )
    source_article_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        for key in ("document_source_ids", "web_source_ids"):
            if len(attrs[key]) != len(set(attrs[key])):
                raise serializers.ValidationError(f"{key} must be unique")
        if len(attrs["document_source_ids"]) + len(attrs["web_source_ids"]) > 12:
            raise serializers.ValidationError("too many supplemental sources")
        if attrs["source_mode"] == "article" and attrs.get("source_article_id") is None:
            raise serializers.ValidationError("source_article_id is required for article mode")
        if attrs["source_mode"] != "article" and not attrs.get("topic", "").strip():
            raise serializers.ValidationError("topic is required")
        return attrs


class VideoScriptSceneSerializer(StrictSerializer):
    scene = serializers.IntegerField(min_value=1, max_value=50)
    start = serializers.FloatField(min_value=0)
    end = serializers.FloatField(min_value=0)
    visual = serializers.CharField(max_length=2_000)
    voiceover = serializers.CharField(max_length=4_000, allow_blank=True, trim_whitespace=False)
    subtitle = serializers.CharField(max_length=1_000, allow_blank=True, trim_whitespace=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs["end"] <= attrs["start"]:
            raise serializers.ValidationError("scene end must be greater than start")
        return attrs


class VideoScriptSaveSerializer(StrictSerializer):
    title = serializers.CharField(max_length=500)
    hooks = serializers.ListField(
        child=serializers.CharField(max_length=400), min_length=3, max_length=3
    )
    scenes = VideoScriptSceneSerializer(many=True, min_length=2, max_length=12)
    full_voiceover = serializers.CharField(max_length=20_000, trim_whitespace=False)
    cta = serializers.CharField(
        max_length=1_000, required=False, allow_blank=True, default="", trim_whitespace=False
    )
    expected_version = serializers.IntegerField(min_value=1)

    def validate_hooks(self, hooks):
        if len({value.strip() for value in hooks}) != 3:
            raise serializers.ValidationError("hooks must be distinct")
        return hooks
