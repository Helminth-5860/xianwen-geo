from django.contrib import admin

from .models import VideoAsset, VideoGenerationJob


@admin.register(VideoGenerationJob)
class VideoGenerationJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "subject",
        "generation_mode",
        "duration_seconds",
        "status",
        "stage",
        "created_at",
    )
    list_filter = ("status", "stage", "generation_mode", "duration_seconds")
    search_fields = ("id", "user__phone", "subject__id")
    readonly_fields = tuple(field.name for field in VideoGenerationJob._meta.fields)


@admin.register(VideoAsset)
class VideoAssetAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "subject",
        "duration_seconds",
        "aspect_ratio",
        "is_subject_library",
        "created_at",
    )
    list_filter = ("is_subject_library", "duration_seconds", "aspect_ratio")
    search_fields = ("id", "user__phone", "subject__id")
    readonly_fields = tuple(field.name for field in VideoAsset._meta.fields)
