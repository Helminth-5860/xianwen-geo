from rest_framework import serializers

from .models import WebsiteProject
from .services import MAX_SELECTED_ASSETS


class WebsiteGenerateSerializer(serializers.Serializer):
    style_key = serializers.ChoiceField(choices=WebsiteProject.Style.values)
    image_asset_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
        max_length=MAX_SELECTED_ASSETS,
    )
