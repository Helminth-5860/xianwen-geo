from django.urls import path

from .generation_views import (
    KeywordGenerationCreateView,
    KeywordGenerationDetailView,
)
from .views import (
    KeywordCommitView,
    KeywordCurrentView,
    KeywordDraftView,
    KeywordVersionDetailView,
    KeywordVersionListView,
)

urlpatterns = [
    path(
        "subjects/<uuid:subject_id>/keywords/generate",
        KeywordGenerationCreateView.as_view(),
    ),
    path(
        "keyword-jobs/<uuid:job_id>",
        KeywordGenerationDetailView.as_view(),
    ),
    path("subjects/<uuid:subject_id>/keywords/draft", KeywordDraftView.as_view()),
    path("subjects/<uuid:subject_id>/keywords/current", KeywordCurrentView.as_view()),
    path("subjects/<uuid:subject_id>/keywords/commit", KeywordCommitView.as_view()),
    path("subjects/<uuid:subject_id>/keywords/versions", KeywordVersionListView.as_view()),
    path(
        "subjects/<uuid:subject_id>/keywords/versions/<uuid:version_id>",
        KeywordVersionDetailView.as_view(),
    ),
]
