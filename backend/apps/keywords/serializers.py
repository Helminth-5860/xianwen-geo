from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .models import KeywordItemFields
from .taxonomy import KEYWORD_CATEGORY_VALUES, KEYWORD_INTENT_VALUES


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
    search_intents = serializers.ListField(
        child=serializers.ChoiceField(choices=sorted(KEYWORD_INTENT_VALUES)),
        required=False,
        allow_empty=True,
        default=list,
    )
    regions = serializers.ListField(
        child=serializers.JSONField(),
        required=False,
        allow_empty=True,
        default=list,
    )
    source = serializers.ChoiceField(
        choices=KeywordItemFields.Source.values,
        required=False,
        default=KeywordItemFields.Source.LEGACY,
    )
    notes = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        default="",
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


class KeywordCandidateInputSerializer(StrictSerializer):
    text = serializers.CharField(max_length=500, trim_whitespace=False, allow_blank=True)
    category = serializers.ChoiceField(choices=sorted(KEYWORD_CATEGORY_VALUES))
    intents = serializers.ListField(
        child=serializers.ChoiceField(choices=sorted(KEYWORD_INTENT_VALUES)),
        allow_empty=False,
        max_length=8,
    )
    length_type = serializers.ChoiceField(
        choices=(KeywordItemFields.StructureType.SHORT, KeywordItemFields.StructureType.LONG_TAIL)
    )
    regions = serializers.ListField(
        child=serializers.JSONField(),
        required=False,
        allow_empty=True,
        default=list,
        max_length=20,
    )
    notes = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        default="",
    )


class KeywordCandidateAppendRequestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=0)
    expected_subject_version_id = serializers.UUIDField()
    source = serializers.ChoiceField(
        choices=(KeywordItemFields.Source.MANUAL, KeywordItemFields.Source.BULK)
    )
    items = KeywordCandidateInputSerializer(many=True, allow_empty=False, max_length=200)


class KeywordAssetPreferenceUpdateSerializer(StrictSerializer):
    display_text = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
    )
    category = serializers.ChoiceField(
        choices=sorted(KEYWORD_CATEGORY_VALUES),
        required=False,
        allow_blank=True,
    )
    intents = serializers.ListField(
        child=serializers.ChoiceField(choices=sorted(KEYWORD_INTENT_VALUES)),
        required=False,
        allow_empty=True,
        max_length=8,
    )
    regions = serializers.ListField(
        child=serializers.JSONField(),
        required=False,
        allow_empty=True,
        max_length=20,
    )
    enabled = serializers.BooleanField(required=False)
    usable_for_questions = serializers.BooleanField(required=False)
    deleted = serializers.BooleanField(required=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not attrs:
            raise serializers.ValidationError("At least one asset preference is required.")
        return attrs
