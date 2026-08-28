from django.urls import path

from .views import (
    AuthorizationSessionView,
    PublicationJobApproveView,
    PublicationJobView,
    SubjectAuthorizationStartView,
    SubjectAutoPublishView,
    SubjectPlatformAccountView,
    SubjectPlatformCatalogView,
    SubjectPublicationJobsView,
)

urlpatterns = [
    path(
        "subjects/<uuid:subject_id>/auto-publish",
        SubjectAutoPublishView.as_view(),
        name="subject-auto-publish",
    ),
    path(
        "subjects/<uuid:subject_id>/auto-publish/platforms",
        SubjectPlatformCatalogView.as_view(),
        name="subject-auto-publish-platforms",
    ),
    path(
        "subjects/<uuid:subject_id>/auto-publish/authorizations",
        SubjectAuthorizationStartView.as_view(),
        name="subject-auto-publish-authorization-start",
    ),
    path(
        "auto-publish/authorizations/<uuid:session_id>",
        AuthorizationSessionView.as_view(),
        name="auto-publish-authorization",
    ),
    path(
        "subjects/<uuid:subject_id>/auto-publish/platforms/<slug:platform_key>/account",
        SubjectPlatformAccountView.as_view(),
        name="subject-auto-publish-platform-account",
    ),
    path(
        "subjects/<uuid:subject_id>/auto-publish/jobs",
        SubjectPublicationJobsView.as_view(),
        name="subject-auto-publish-jobs",
    ),
    path(
        "auto-publish/jobs/<uuid:job_id>",
        PublicationJobView.as_view(),
        name="auto-publish-job",
    ),
    path(
        "auto-publish/jobs/<uuid:job_id>/approve",
        PublicationJobApproveView.as_view(),
        name="auto-publish-job-approve",
    ),
]
