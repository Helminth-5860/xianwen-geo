from django.urls import path

from .views import (
    PublishingAuthorizationSessionView,
    SubjectPlatformAccountView,
    SubjectPublicationCreateView,
    SubjectPublishingAuthorizationStartView,
    SubjectPublishingPreferenceView,
    SubjectPublishingStateView,
)
from .wechat_component import WechatComponentCallbackView, WechatComponentEventView

urlpatterns = [
    path(
        "subjects/<uuid:subject_id>/publishing",
        SubjectPublishingStateView.as_view(),
        name="subject-publishing-state",
    ),
    path(
        "subjects/<uuid:subject_id>/publishing/preferences",
        SubjectPublishingPreferenceView.as_view(),
        name="subject-publishing-preference",
    ),
    path(
        "subjects/<uuid:subject_id>/publishing/authorization-sessions",
        SubjectPublishingAuthorizationStartView.as_view(),
        name="subject-publishing-authorization-start",
    ),
    path(
        "publishing/authorization-sessions/<uuid:session_id>",
        PublishingAuthorizationSessionView.as_view(),
        name="publishing-authorization-session",
    ),
    path(
        "subjects/<uuid:subject_id>/publishing/accounts/<str:platform_key>",
        SubjectPlatformAccountView.as_view(),
        name="subject-publishing-platform-account",
    ),
    path(
        "subjects/<uuid:subject_id>/publishing/publications",
        SubjectPublicationCreateView.as_view(),
        name="subject-publication-create",
    ),
    path(
        "publishing/wechat/component/events",
        WechatComponentEventView.as_view(),
        name="wechat-component-events",
    ),
    path(
        "publishing/wechat/component/callback",
        WechatComponentCallbackView.as_view(),
        name="wechat-component-callback",
    ),
]
