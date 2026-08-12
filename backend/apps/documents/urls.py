from django.urls import path

from .parse_views import (
    DocumentConfirmParseView,
    DocumentParseResultView,
    DocumentParseView,
)
from .views import (
    DocumentDownloadIntentView,
    SubjectDocumentListView,
    UploadIntentCompleteView,
    UploadIntentDetailView,
    UploadIntentListView,
)

urlpatterns = [
    path("files/upload-intents", UploadIntentListView.as_view(), name="file-upload-intents"),
    path(
        "files/upload-intents/<uuid:intent_id>",
        UploadIntentDetailView.as_view(),
        name="file-upload-intent-detail",
    ),
    path(
        "files/upload-intents/<uuid:intent_id>/complete",
        UploadIntentCompleteView.as_view(),
        name="file-upload-intent-complete",
    ),
    path(
        "subjects/<uuid:subject_id>/documents",
        SubjectDocumentListView.as_view(),
        name="subject-documents",
    ),
    path(
        "documents/<uuid:document_id>/download-intents",
        DocumentDownloadIntentView.as_view(),
        name="document-download-intent",
    ),
    path(
        "documents/<uuid:document_id>/parse",
        DocumentParseView.as_view(),
        name="document-parse",
    ),
    path(
        "documents/<uuid:document_id>/parse-result",
        DocumentParseResultView.as_view(),
        name="document-parse-result",
    ),
    path(
        "documents/<uuid:document_id>/confirm",
        DocumentConfirmParseView.as_view(),
        name="document-parse-confirm",
    ),
]
