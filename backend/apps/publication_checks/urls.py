from django.urls import path

from .views import (
    PublicationVerificationBulkDeleteView,
    PublicationVerificationDetailView,
    SubjectPublicationVerificationView,
)

urlpatterns = [
    path(
        "subjects/<uuid:subject_id>/publication-verifications",
        SubjectPublicationVerificationView.as_view(),
        name="subject-publication-verifications",
    ),
    path(
        "subjects/<uuid:subject_id>/publication-verifications/bulk-delete",
        PublicationVerificationBulkDeleteView.as_view(),
        name="subject-publication-verifications-bulk-delete",
    ),
    path(
        "subjects/<uuid:subject_id>/publication-verifications/<uuid:check_id>",
        PublicationVerificationDetailView.as_view(),
        name="subject-publication-verification",
    ),
]
