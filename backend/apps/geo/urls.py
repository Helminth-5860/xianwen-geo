from django.urls import path

from .views import (
    GeoDetectionCancelView,
    GeoDetectionCreateView,
    GeoDetectionDetailView,
    GeoDetectionEstimateView,
    GeoDetectionModelProgressView,
    GeoDetectionOptionsView,
    GeoModelsView,
)

urlpatterns = [
    path("geo/models", GeoModelsView.as_view(), name="geo-models"),
    path(
        "subjects/<uuid:subject_id>/geo/detection-options",
        GeoDetectionOptionsView.as_view(),
        name="geo-detection-options",
    ),
    path(
        "subjects/<uuid:subject_id>/geo/estimate",
        GeoDetectionEstimateView.as_view(),
        name="geo-detection-estimate",
    ),
    path(
        "subjects/<uuid:subject_id>/geo/detections",
        GeoDetectionCreateView.as_view(),
        name="geo-detection-create",
    ),
    path(
        "geo/detections/<uuid:detection_id>",
        GeoDetectionDetailView.as_view(),
        name="geo-detection-detail",
    ),
    path(
        "geo/detections/<uuid:detection_id>/model-progress",
        GeoDetectionModelProgressView.as_view(),
        name="geo-detection-model-progress",
    ),
    path(
        "geo/detections/<uuid:detection_id>/cancel",
        GeoDetectionCancelView.as_view(),
        name="geo-detection-cancel",
    ),
]
