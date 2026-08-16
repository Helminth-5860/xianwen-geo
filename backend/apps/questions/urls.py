from django.urls import path

from .views import (
    AdminQuestionCategoryDetailView,
    AdminQuestionCategoryDisableView,
    AdminQuestionCategoryEnableView,
    AdminQuestionCategoryListView,
    AdminQuestionTagDetailView,
    AdminQuestionTagDisableView,
    AdminQuestionTagEnableView,
    AdminQuestionTagListView,
    PublicQuestionCatalogView,
)

urlpatterns = [
    path(
        "question-categories", PublicQuestionCatalogView.as_view(), name="question-catalog-public"
    ),
    path(
        "admin/question-categories",
        AdminQuestionCategoryListView.as_view(),
        name="admin-question-categories",
    ),
    path(
        "admin/question-categories/<uuid:category_id>",
        AdminQuestionCategoryDetailView.as_view(),
        name="admin-question-category-detail",
    ),
    path(
        "admin/question-categories/<uuid:category_id>/enable",
        AdminQuestionCategoryEnableView.as_view(),
        name="admin-question-category-enable",
    ),
    path(
        "admin/question-categories/<uuid:category_id>/disable",
        AdminQuestionCategoryDisableView.as_view(),
        name="admin-question-category-disable",
    ),
    path("admin/question-tags", AdminQuestionTagListView.as_view(), name="admin-question-tags"),
    path(
        "admin/question-tags/<uuid:tag_id>",
        AdminQuestionTagDetailView.as_view(),
        name="admin-question-tag-detail",
    ),
    path(
        "admin/question-tags/<uuid:tag_id>/enable",
        AdminQuestionTagEnableView.as_view(),
        name="admin-question-tag-enable",
    ),
    path(
        "admin/question-tags/<uuid:tag_id>/disable",
        AdminQuestionTagDisableView.as_view(),
        name="admin-question-tag-disable",
    ),
]
