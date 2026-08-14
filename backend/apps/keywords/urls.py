from django.urls import path

from .views import (
    KeywordCommitView,
    KeywordCurrentView,
    KeywordDraftView,
    KeywordVersionDetailView,
    KeywordVersionListView,
)

urlpatterns = [
    path("subjects/<uuid:subject_id>/keywords/draft", KeywordDraftView.as_view()),
    path("subjects/<uuid:subject_id>/keywords/current", KeywordCurrentView.as_view()),
    path("subjects/<uuid:subject_id>/keywords/commit", KeywordCommitView.as_view()),
    path("subjects/<uuid:subject_id>/keywords/versions", KeywordVersionListView.as_view()),
    path(
        "subjects/<uuid:subject_id>/keywords/versions/<uuid:version_id>",
        KeywordVersionDetailView.as_view(),
    ),
]
