from rest_framework import serializers

from .models import WebsiteProject
from .services import MAX_SELECTED_MATERIALS


class WebsiteGenerateSerializer(serializers.Serializer):
    style_key = serializers.ChoiceField(choices=WebsiteProject.Style.values)
    theme_key = serializers.ChoiceField(choices=WebsiteProject.Theme.values)
    density_key = serializers.ChoiceField(choices=WebsiteProject.Density.values)
    image_asset_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
        max_length=MAX_SELECTED_MATERIALS,
    )
    document_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
        max_length=MAX_SELECTED_MATERIALS,
    )

    def validate(self, attrs):
        total = len(attrs.get("image_asset_ids", [])) + len(attrs.get("document_ids", []))
        if total > MAX_SELECTED_MATERIALS:
            raise serializers.ValidationError(
                {"document_ids": [f"官网素材最多选择 {MAX_SELECTED_MATERIALS} 张图片"]}
            )
        return attrs


class WebsiteDesignSerializer(serializers.Serializer):
    style_key = serializers.ChoiceField(choices=WebsiteProject.Style.values)
    theme_key = serializers.ChoiceField(choices=WebsiteProject.Theme.values)
    density_key = serializers.ChoiceField(choices=WebsiteProject.Density.values)
    expected_version = serializers.IntegerField(min_value=1)
