from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .models import ImageDerivative, ImageGenerationJob


class GenerateImageItemSerializer(StrictSerializer):
    article_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    role = serializers.ChoiceField(choices=ImageGenerationJob.Role.values)
    prompt = serializers.CharField(max_length=4000, trim_whitespace=False)
    size_preset_id = serializers.UUIDField()
    style_preset_id = serializers.UUIDField()
    reference_asset_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    reference_document_version_id = serializers.UUIDField(
        required=False, allow_null=True, default=None
    )
    reference_url = serializers.URLField(
        required=False, allow_blank=True, default="", max_length=4096
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        references = (
            attrs.get("reference_asset_id"),
            attrs.get("reference_document_version_id"),
            attrs.get("reference_url"),
        )
        if sum(bool(value) for value in references) > 1:
            raise serializers.ValidationError("Only one reference image is allowed.")
        return attrs


class GenerateImagesSerializer(StrictSerializer):
    article_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    role = serializers.ChoiceField(choices=ImageGenerationJob.Role.values, required=False)
    prompt = serializers.CharField(max_length=4000, trim_whitespace=False, required=False)
    size_preset_id = serializers.UUIDField(required=False)
    style_preset_id = serializers.UUIDField(required=False)
    reference_asset_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    reference_document_version_id = serializers.UUIDField(
        required=False, allow_null=True, default=None
    )
    reference_url = serializers.URLField(
        required=False, allow_blank=True, default="", max_length=4096
    )
    items = GenerateImageItemSerializer(many=True, required=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        items = attrs.get("items")
        if items and len(items) > 20:
            raise serializers.ValidationError("At most 20 image requests are allowed.")
        singular_fields = {
            "role",
            "prompt",
            "size_preset_id",
            "style_preset_id",
        }
        has_singular = singular_fields.issubset(attrs)
        if bool(items) == has_singular:
            raise serializers.ValidationError("Provide either one image request or items.")
        if has_singular:
            references = (
                attrs.get("reference_asset_id"),
                attrs.get("reference_document_version_id"),
                attrs.get("reference_url"),
            )
            if sum(bool(value) for value in references) > 1:
                raise serializers.ValidationError("Only one reference image is allowed.")
        return attrs


class ExpectedImageVersionSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)


class AttachImageSerializer(ExpectedImageVersionSerializer):
    article_id = serializers.UUIDField()


class ImageDerivativeSerializer(StrictSerializer):
    ai = serializers.BooleanField(default=False)
    kind = serializers.ChoiceField(choices=ImageDerivative.Kind.values, required=False)
    width = serializers.IntegerField(min_value=1, max_value=8192, required=False)
    height = serializers.IntegerField(min_value=1, max_value=8192, required=False)
    output_format = serializers.ChoiceField(choices=("png", "jpeg", "webp"), required=False)
    prompt = serializers.CharField(max_length=4000, trim_whitespace=False, required=False)
    size_preset_id = serializers.UUIDField(required=False)
    style_preset_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs["ai"]:
            required = {"prompt", "size_preset_id", "style_preset_id"}
            if not required.issubset(attrs):
                raise serializers.ValidationError(
                    "AI processing requires prompt, size_preset_id and style_preset_id."
                )
            if any(field in attrs for field in ("kind", "width", "height", "output_format")):
                raise serializers.ValidationError(
                    "AI processing does not accept ordinary derivative parameters."
                )
        else:
            required = {"kind", "width", "height", "output_format"}
            if not required.issubset(attrs):
                raise serializers.ValidationError(
                    "Ordinary processing requires kind, width, height and output_format."
                )
            if attrs["kind"] == ImageDerivative.Kind.AI_EDIT:
                raise serializers.ValidationError("ai_edit requires ai=true.")
            if any(field in attrs for field in ("prompt", "size_preset_id", "style_preset_id")):
                raise serializers.ValidationError(
                    "Ordinary processing does not accept AI generation parameters."
                )
        return attrs


class ImageBatchDownloadSerializer(StrictSerializer):
    subject_id = serializers.UUIDField()
    image_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, max_length=100
    )

    def validate_image_ids(self, values):
        if len(values) != len(set(values)):
            raise serializers.ValidationError("image_ids must be unique")
        return values


class ModerationAppealSerializer(StrictSerializer):
    note = serializers.CharField(max_length=1000, allow_blank=True, default="")


class ImagePresetWriteSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(required=False, min_value=1)
    key = serializers.RegexField(r"^[a-z0-9][a-z0-9_-]{0,63}$", required=False)
    name = serializers.CharField(max_length=100, required=False)
    status = serializers.ChoiceField(choices=("active", "disabled"), required=False)
    sort_order = serializers.IntegerField(required=False, min_value=0)


class ImageSizePresetWriteSerializer(ImagePresetWriteSerializer):
    aspect_ratio = serializers.CharField(max_length=32, required=False)
    width = serializers.IntegerField(required=False, min_value=1, max_value=8192)
    height = serializers.IntegerField(required=False, min_value=1, max_value=8192)
    provider_params = serializers.DictField(required=False)
    applicable_channels = serializers.ListField(
        child=serializers.CharField(max_length=64), required=False, max_length=50
    )
    applicable_roles = serializers.ListField(
        child=serializers.ChoiceField(choices=ImageGenerationJob.Role.values),
        required=False,
        max_length=3,
    )


class ImageStylePresetWriteSerializer(ImagePresetWriteSerializer):
    description = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    prompt_template = serializers.CharField(required=False, max_length=4000)
    applicable_roles = serializers.ListField(
        child=serializers.ChoiceField(choices=ImageGenerationJob.Role.values),
        required=False,
        max_length=3,
    )

    def validate_prompt_template(self, value):
        if "{prompt}" not in value:
            raise serializers.ValidationError("prompt_template must include {prompt}")
        return value
