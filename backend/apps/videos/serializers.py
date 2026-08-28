from django.conf import settings
from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .models import VideoGenerationJob


class VideoJobCreateSerializer(StrictSerializer):
    generation_mode = serializers.ChoiceField(
        choices=VideoGenerationJob.GenerationMode.values,
        error_messages={"invalid_choice": "请选择文字生成视频或图片生成视频。"},
    )
    prompt = serializers.CharField(
        max_length=settings.VIDEO_PROMPT_MAX_LENGTH,
        trim_whitespace=True,
        error_messages={
            "required": "请输入视频内容描述。",
            "blank": "请输入视频内容描述。",
            "max_length": "视频内容描述最多可填写 1500 个字。",
        },
    )
    source_document_version_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        error_messages={"invalid": "参考图片不可用，请重新选择。"},
    )
    aspect_ratio = serializers.ChoiceField(
        choices=VideoGenerationJob.AspectRatio.values,
        error_messages={"invalid_choice": "视频比例仅支持 9:16 或 16:9。"},
    )
    duration_seconds = serializers.ChoiceField(
        choices=settings.VIDEO_ALLOWED_DURATIONS,
        error_messages={"invalid_choice": "视频时长仅支持 5 秒或 10 秒。"},
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        source_id = attrs.get("source_document_version_id")
        if attrs["generation_mode"] == VideoGenerationJob.GenerationMode.IMAGE and not source_id:
            raise serializers.ValidationError("图片生成视频时请选择一张图片。")
        if attrs["generation_mode"] == VideoGenerationJob.GenerationMode.TEXT and source_id:
            raise serializers.ValidationError("文字生成视频时不需要选择图片。")
        if not attrs["prompt"].strip():
            raise serializers.ValidationError("请输入视频内容描述。")
        return attrs


class ExpectedVideoVersionSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)


class EmptyVideoActionSerializer(StrictSerializer):
    pass
