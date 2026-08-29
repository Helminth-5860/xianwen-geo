from django.urls import path

from .views import (
    NegativeIndexEventDetailView,
    NegativeIndexEventListView,
    NegativeIndexScanCreateView,
    NegativeIndexScanDetailView,
    SubjectNegativeIndexView,
)

urlpatterns = [
    path("subjects/<uuid:subject_id>/negative-index/", SubjectNegativeIndexView.as_view(), name="subject-negative-index"),
    path("subjects/<uuid:subject_id>/negative-index/scans/", NegativeIndexScanCreateView.as_view(), name="negative-index-scan-create"),
    path("negative-index/scans/<uuid:scan_id>/", NegativeIndexScanDetailView.as_view(), name="negative-index-scan-detail"),
    path("negative-index/scans/<uuid:scan_id>/events/", NegativeIndexEventListView.as_view(), name="negative-index-event-list"),
    path("negative-index/events/<uuid:event_id>/", NegativeIndexEventDetailView.as_view(), name="negative-index-event-detail"),
]
