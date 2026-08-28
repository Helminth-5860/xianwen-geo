from django.urls import path

from .views import (
    SubjectVideoJobsView,
    SubjectVideosView,
    VideoContentView,
    VideoJobDownloadIntentView,
    VideoJobRegenerateView,
    VideoJobSaveLibraryView,
    VideoJobView,
)

urlpatterns = [
    path(
        "subjects/<uuid:subject_id>/video-jobs",
        SubjectVideoJobsView.as_view(),
        name="subject-video-jobs",
    ),
    path("video-jobs/<uuid:job_id>", VideoJobView.as_view(), name="video-job"),
    path(
        "video-jobs/<uuid:job_id>/regenerate",
        VideoJobRegenerateView.as_view(),
        name="video-job-regenerate",
    ),
    path(
        "video-jobs/<uuid:job_id>/download-intents",
        VideoJobDownloadIntentView.as_view(),
        name="video-job-download-intent",
    ),
    path(
        "video-jobs/<uuid:job_id>/save-to-library",
        VideoJobSaveLibraryView.as_view(),
        name="video-job-save-library",
    ),
    path(
        "subjects/<uuid:subject_id>/videos",
        SubjectVideosView.as_view(),
        name="subject-videos",
    ),
    path(
        "subjects/<uuid:subject_id>/videos/<uuid:video_id>/content",
        VideoContentView.as_view(),
        name="video-content",
    ),
]
