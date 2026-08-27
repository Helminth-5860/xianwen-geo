from django.urls import path

from .views import (
    AdminSizePresetDetailView,
    AdminSizePresetListCreateView,
    AdminStylePresetDetailView,
    AdminStylePresetListCreateView,
    ImageAppealView,
    ImageAttachView,
    ImageBatchDownloadView,
    ImageContentView,
    ImageDerivativeView,
    ImageDetailView,
    ImageGenerateView,
    ImageJobView,
    ImageRecommendationView,
    ImageRestoreView,
    ImageSaveLibraryView,
    ImageSizeListView,
    ImageStyleListView,
    SubjectImagesView,
)

urlpatterns = [
    path("image-sizes", ImageSizeListView.as_view(), name="image-sizes"),
    path("image-styles", ImageStyleListView.as_view(), name="image-styles"),
    path(
        "articles/<uuid:article_id>/image-recommendations",
        ImageRecommendationView.as_view(),
        name="article-image-recommendations",
    ),
    path(
        "subjects/<uuid:subject_id>/images/generate",
        ImageGenerateView.as_view(),
        name="image-generate",
    ),
    path("image-jobs/<uuid:job_id>", ImageJobView.as_view(), name="image-job"),
    path(
        "subjects/<uuid:subject_id>/images",
        SubjectImagesView.as_view(),
        name="subject-images",
    ),
    path(
        "subjects/<uuid:subject_id>/images/<uuid:image_id>/content",
        ImageContentView.as_view(),
        name="image-content",
    ),
    path(
        "images/<uuid:image_id>/save-to-library",
        ImageSaveLibraryView.as_view(),
        name="image-save-to-library",
    ),
    path("images/<uuid:image_id>/attach", ImageAttachView.as_view(), name="image-attach"),
    path("images/<uuid:image_id>/derive", ImageDerivativeView.as_view(), name="image-derive"),
    path("images/batch-download", ImageBatchDownloadView.as_view(), name="image-batch-download"),
    path("images/<uuid:image_id>", ImageDetailView.as_view(), name="image-detail"),
    path("images/<uuid:image_id>/restore", ImageRestoreView.as_view(), name="image-restore"),
    path(
        "images/<uuid:image_id>/moderation/appeal",
        ImageAppealView.as_view(),
        name="image-moderation-appeal",
    ),
    path(
        "admin/image-sizes",
        AdminSizePresetListCreateView.as_view(),
        name="admin-image-sizes",
    ),
    path(
        "admin/image-sizes/<uuid:preset_id>",
        AdminSizePresetDetailView.as_view(),
        name="admin-image-size",
    ),
    path(
        "admin/image-styles",
        AdminStylePresetListCreateView.as_view(),
        name="admin-image-styles",
    ),
    path(
        "admin/image-styles/<uuid:preset_id>",
        AdminStylePresetDetailView.as_view(),
        name="admin-image-style",
    ),
]
