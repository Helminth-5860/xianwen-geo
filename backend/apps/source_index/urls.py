from django.urls import path

from .views import (
    SourceIndexScanCreateView,
    SourceIndexScanDetailView,
    SourceIndexSourceListView,
    SubjectSourceIndexView,
)

urlpatterns = [
    path(
        "subjects/<uuid:subject_id>/source-index/",
        SubjectSourceIndexView.as_view(),
        name="subject-source-index",
    ),
    path(
        "subjects/<uuid:subject_id>/source-index/scans/",
        SourceIndexScanCreateView.as_view(),
        name="source-index-scan-create",
    ),
    path(
        "source-index/scans/<uuid:scan_id>/",
        SourceIndexScanDetailView.as_view(),
        name="source-index-scan-detail",
    ),
    path(
        "source-index/scans/<uuid:scan_id>/sources/",
        SourceIndexSourceListView.as_view(),
        name="source-index-source-list",
    ),
]
