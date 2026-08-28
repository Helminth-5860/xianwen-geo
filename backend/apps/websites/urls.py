from django.urls import path

from .views import (
    SubjectWebsiteDesignView,
    SubjectWebsiteGenerateView,
    SubjectWebsiteView,
    WebsiteGenerationJobView,
)

urlpatterns = [
    path("subjects/<uuid:subject_id>/website", SubjectWebsiteView.as_view(), name="subject-website"),
    path(
        "subjects/<uuid:subject_id>/website/generate",
        SubjectWebsiteGenerateView.as_view(),
        name="subject-website-generate",
    ),
    path(
        "subjects/<uuid:subject_id>/website/design",
        SubjectWebsiteDesignView.as_view(),
        name="subject-website-design",
    ),
    path(
        "website-jobs/<uuid:job_id>",
        WebsiteGenerationJobView.as_view(),
        name="website-generation-job",
    ),
]
