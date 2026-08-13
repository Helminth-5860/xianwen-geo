from django.urls import path

from .views import (
    SubjectWebSourceListView,
    WebSourceConfirmView,
    WebSourceImportCreateView,
    WebSourceImportDetailView,
)

urlpatterns = [
    path("web-sources/import", WebSourceImportCreateView.as_view(), name="web-source-import"),
    path(
        "web-sources/<uuid:import_id>",
        WebSourceImportDetailView.as_view(),
        name="web-source-detail",
    ),
    path(
        "subjects/<uuid:subject_id>/web-sources",
        SubjectWebSourceListView.as_view(),
        name="subject-web-sources",
    ),
    path(
        "web-sources/<uuid:import_id>/confirm",
        WebSourceConfirmView.as_view(),
        name="web-source-confirm",
    ),
]
