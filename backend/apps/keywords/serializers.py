from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .models import KeywordItemFields


class KeywordDraftItemInputSerializer(StrictSerializer):
    text = serializers.CharField(max_length=500, trim_whitespace=False)
    structure_type = serializers.ChoiceField(choices=KeywordItemFields.StructureType.values)
    is_regional = serializers.BooleanField()
    region_level = serializers.ChoiceField(
        choices=["", *KeywordItemFields.RegionLevel.values],
        required=False,
        allow_blank=True,
        default="",
    )
    region_text = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        default="",
    )


class KeywordDraftSaveRequestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=0)
    expected_subject_version_id = serializers.UUIDField()
    items = KeywordDraftItemInputSerializer(many=True)


class KeywordCommitRequestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    expected_subject_version_id = serializers.UUIDField()
