from django.urls import path

from .subject_views import (
    SubjectActivateView,
    SubjectArchiveView,
    SubjectCurrentView,
    SubjectDetailView,
    SubjectDraftView,
    SubjectListCreateView,
)
from .views import (
    AdminSubjectFieldOptionDetailView,
    AdminSubjectFieldOptionListView,
    AdminSubjectTypeDetailView,
    AdminSubjectTypeDisableView,
    AdminSubjectTypeEnableView,
    AdminSubjectTypeFieldDetailView,
    AdminSubjectTypeFieldListView,
    AdminSubjectTypeFieldOrderView,
    AdminSubjectTypeListView,
    PublicSubjectFormSchemaView,
    PublicSubjectTypeListView,
)

urlpatterns = [
    path("subject-types", PublicSubjectTypeListView.as_view(), name="subject-type-list"),
    path("subjects", SubjectListCreateView.as_view(), name="subject-list-create"),
    path("subjects/current", SubjectCurrentView.as_view(), name="subject-current"),
    path(
        "subjects/<uuid:subject_id>",
        SubjectDetailView.as_view(),
        name="subject-detail",
    ),
    path(
        "subjects/<uuid:subject_id>/draft",
        SubjectDraftView.as_view(),
        name="subject-draft",
    ),
    path(
        "subjects/<uuid:subject_id>/activate",
        SubjectActivateView.as_view(),
        name="subject-activate",
    ),
    path(
        "subjects/<uuid:subject_id>/archive",
        SubjectArchiveView.as_view(),
        name="subject-archive",
    ),
    path(
        "subject-types/<uuid:subject_type_id>/form-schema",
        PublicSubjectFormSchemaView.as_view(),
        name="subject-form-schema",
    ),
    path("admin/subject-types", AdminSubjectTypeListView.as_view(), name="admin-subject-types"),
    path(
        "admin/subject-types/<uuid:subject_type_id>",
        AdminSubjectTypeDetailView.as_view(),
        name="admin-subject-type-detail",
    ),
    path(
        "admin/subject-types/<uuid:subject_type_id>/enable",
        AdminSubjectTypeEnableView.as_view(),
        name="admin-subject-type-enable",
    ),
    path(
        "admin/subject-types/<uuid:subject_type_id>/disable",
        AdminSubjectTypeDisableView.as_view(),
        name="admin-subject-type-disable",
    ),
    path(
        "admin/subject-types/<uuid:subject_type_id>/fields",
        AdminSubjectTypeFieldListView.as_view(),
        name="admin-subject-type-fields",
    ),
    path(
        "admin/subject-types/<uuid:subject_type_id>/field-order",
        AdminSubjectTypeFieldOrderView.as_view(),
        name="admin-subject-type-field-order",
    ),
    path(
        "admin/subject-type-fields/<uuid:config_id>",
        AdminSubjectTypeFieldDetailView.as_view(),
        name="admin-subject-type-field-detail",
    ),
    path(
        "admin/subject-type-fields/<uuid:config_id>/options",
        AdminSubjectFieldOptionListView.as_view(),
        name="admin-subject-field-options",
    ),
    path(
        "admin/subject-field-options/<uuid:option_id>",
        AdminSubjectFieldOptionDetailView.as_view(),
        name="admin-subject-field-option-detail",
    ),
]
