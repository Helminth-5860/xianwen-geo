from django.urls import path

from .views import SubjectWebsiteGenerateView, SubjectWebsiteView, WebsiteGenerationJobView

urlpatterns = [
    path("subjects/<uuid:subject_id>/website", SubjectWebsiteView.as_view(), name="subject-website"),
    path(
        "subjects/<uuid:subject_id>/website/generate",
        SubjectWebsiteGenerateView.as_view(),
        name="subject-website-generate",
    ),
    path(
        "website-jobs/<uuid:job_id>",
        WebsiteGenerationJobView.as_view(),
        name="website-generation-job",
    ),
]
