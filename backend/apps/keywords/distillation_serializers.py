from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .models import DistillationActionFields


class DistillationCreateSerializer(StrictSerializer):
    keyword_set_version_id = serializers.UUIDField()
    expected_workspace_version = serializers.IntegerField(min_value=0)
    regenerate = serializers.BooleanField(default=False)


class DistillationDraftItemInputSerializer(StrictSerializer):
    source_keyword_id = serializers.UUIDField()
    action = serializers.ChoiceField(choices=DistillationActionFields.Action.values)
    canonical_keyword_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    merge_group_key = serializers.UUIDField(required=False, allow_null=True, default=None)
    user_reason = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        default="",
    )


class DistillationDraftSaveSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    items = DistillationDraftItemInputSerializer(many=True)


class DistillationConfirmSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
