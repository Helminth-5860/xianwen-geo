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
    id = serializers.UUIDField(required=False)
    base_keyword_text = serializers.CharField(
        max_length=500,
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
        default=None,
    )
    business_category = serializers.CharField(
        max_length=128,
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
        default=None,
    )
    search_intent = serializers.ChoiceField(
        choices=KeywordItemFields.SearchIntent.values,
        required=False,
        allow_null=True,
        default=None,
    )
    relevance_score = serializers.IntegerField(
        min_value=0,
        max_value=100,
        required=False,
        allow_null=True,
        default=None,
    )
    priority = serializers.ChoiceField(
        choices=KeywordItemFields.Priority.values,
        required=False,
        allow_null=True,
        default=None,
    )
    ai_reason = serializers.CharField(
        max_length=1000,
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
        default=None,
    )


class KeywordDraftSaveRequestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=0)
    expected_subject_version_id = serializers.UUIDField()
    items = KeywordDraftItemInputSerializer(many=True)


class KeywordCommitRequestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    expected_subject_version_id = serializers.UUIDField()
