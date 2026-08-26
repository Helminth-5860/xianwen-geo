from django.urls import path

from .generation_views import (
    QuestionBankBulkRemoveView,
    QuestionBankConfirmView,
    QuestionBankCurrentView,
    QuestionBankDraftView,
    QuestionBankVersionDetailView,
    QuestionBankVersionListView,
    QuestionGenerationCreateView,
    QuestionGenerationJobDetailView,
)
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
        "subjects/<uuid:subject_id>/question-banks/generate", QuestionGenerationCreateView.as_view()
    ),
    path("question-bank-jobs/<uuid:job_id>", QuestionGenerationJobDetailView.as_view()),
    path("subjects/<uuid:subject_id>/question-banks/draft", QuestionBankDraftView.as_view()),
    path("subjects/<uuid:subject_id>/question-banks/confirm", QuestionBankConfirmView.as_view()),
    path("subjects/<uuid:subject_id>/question-banks/current", QuestionBankCurrentView.as_view()),
    path(
        "subjects/<uuid:subject_id>/question-banks/remove",
        QuestionBankBulkRemoveView.as_view(),
    ),
    path(
        "subjects/<uuid:subject_id>/question-banks/versions", QuestionBankVersionListView.as_view()
    ),
    path(
        "subjects/<uuid:subject_id>/question-banks/versions/<uuid:version_id>",
        QuestionBankVersionDetailView.as_view(),
    ),
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
