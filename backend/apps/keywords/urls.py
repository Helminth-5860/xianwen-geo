from django.urls import path

from .distillation_views import (
    DistillationConfirmView,
    DistillationCreateView,
    DistillationCurrentView,
    DistillationDraftView,
    DistillationJobDetailView,
)
from .generation_views import (
    KeywordGenerationCreateView,
    KeywordGenerationDetailView,
)
from .views import (
    KeywordAssetListView,
    KeywordAssetPreferenceView,
    KeywordCandidateAppendView,
    KeywordCommitView,
    KeywordCurrentView,
    KeywordDraftView,
    KeywordVersionDetailView,
    KeywordVersionListView,
)

urlpatterns = [
    path("subjects/<uuid:subject_id>/distillations", DistillationCreateView.as_view()),
    path("distillation-jobs/<uuid:job_id>", DistillationJobDetailView.as_view()),
    path(
        "subjects/<uuid:subject_id>/distillations/current",
        DistillationCurrentView.as_view(),
    ),
    path(
        "subjects/<uuid:subject_id>/distillations/draft",
        DistillationDraftView.as_view(),
    ),
    path(
        "subjects/<uuid:subject_id>/distillations/confirm",
        DistillationConfirmView.as_view(),
    ),
    path(
        "subjects/<uuid:subject_id>/keywords/generate",
        KeywordGenerationCreateView.as_view(),
    ),
    path(
        "keyword-jobs/<uuid:job_id>",
        KeywordGenerationDetailView.as_view(),
    ),
    path("subjects/<uuid:subject_id>/keywords/draft", KeywordDraftView.as_view()),
    path(
        "subjects/<uuid:subject_id>/keywords/candidates",
        KeywordCandidateAppendView.as_view(),
    ),
    path(
        "subjects/<uuid:subject_id>/keyword-assets",
        KeywordAssetListView.as_view(),
    ),
    path(
        "subjects/<uuid:subject_id>/keyword-assets/<uuid:keyword_id>",
        KeywordAssetPreferenceView.as_view(),
    ),
    path("subjects/<uuid:subject_id>/keywords/current", KeywordCurrentView.as_view()),
    path("subjects/<uuid:subject_id>/keywords/commit", KeywordCommitView.as_view()),
    path("subjects/<uuid:subject_id>/keywords/versions", KeywordVersionListView.as_view()),
    path(
        "subjects/<uuid:subject_id>/keywords/versions/<uuid:version_id>",
        KeywordVersionDetailView.as_view(),
    ),
]
