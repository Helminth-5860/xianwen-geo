from django.urls import path

from .application_views import (
    AdminPlanApplicationCloseView,
    AdminPlanApplicationContactView,
    AdminPlanApplicationDetailView,
    AdminPlanApplicationListView,
    PlanApplicationCancelView,
    PlanApplicationDetailView,
    PlanApplicationListCreateView,
)
from .views import (
    AdminPlanArchiveView,
    AdminPlanCopyView,
    AdminPlanDetailView,
    AdminPlanLimitDefinitionListView,
    AdminPlanListView,
    AdminPlanOfflineView,
    AdminPlanOnlineView,
    AdminPlanVersionDetailView,
    AdminPlanVersionListView,
    AdminPlanVersionPublishView,
    AdminPlanVersionRetireView,
    PublicPlanDetailView,
    PublicPlanListView,
)

urlpatterns = [
    path("admin/plans", AdminPlanListView.as_view(), name="admin-plan-list"),
    path(
        "admin/plan-limit-definitions",
        AdminPlanLimitDefinitionListView.as_view(),
        name="admin-plan-limit-definitions",
    ),
    path("admin/plans/<uuid:plan_id>", AdminPlanDetailView.as_view(), name="admin-plan-detail"),
    path("admin/plans/<uuid:plan_id>/copy", AdminPlanCopyView.as_view(), name="admin-plan-copy"),
    path(
        "admin/plans/<uuid:plan_id>/online", AdminPlanOnlineView.as_view(), name="admin-plan-online"
    ),
    path(
        "admin/plans/<uuid:plan_id>/offline",
        AdminPlanOfflineView.as_view(),
        name="admin-plan-offline",
    ),
    path(
        "admin/plans/<uuid:plan_id>/archive",
        AdminPlanArchiveView.as_view(),
        name="admin-plan-archive",
    ),
    path(
        "admin/plans/<uuid:plan_id>/versions",
        AdminPlanVersionListView.as_view(),
        name="admin-plan-version-list",
    ),
    path(
        "admin/plan-versions/<uuid:version_id>",
        AdminPlanVersionDetailView.as_view(),
        name="admin-plan-version-detail",
    ),
    path(
        "admin/plan-versions/<uuid:version_id>/publish",
        AdminPlanVersionPublishView.as_view(),
        name="admin-plan-version-publish",
    ),
    path(
        "admin/plan-versions/<uuid:version_id>/retire",
        AdminPlanVersionRetireView.as_view(),
        name="admin-plan-version-retire",
    ),
    path(
        "plan-applications",
        PlanApplicationListCreateView.as_view(),
        name="plan-application-list-create",
    ),
    path(
        "plan-applications/<uuid:application_id>",
        PlanApplicationDetailView.as_view(),
        name="plan-application-detail",
    ),
    path(
        "plan-applications/<uuid:application_id>/cancel",
        PlanApplicationCancelView.as_view(),
        name="plan-application-cancel",
    ),
    path(
        "admin/plan-applications",
        AdminPlanApplicationListView.as_view(),
        name="admin-plan-application-list",
    ),
    path(
        "admin/plan-applications/<uuid:application_id>",
        AdminPlanApplicationDetailView.as_view(),
        name="admin-plan-application-detail",
    ),
    path(
        "admin/plan-applications/<uuid:application_id>/contact",
        AdminPlanApplicationContactView.as_view(),
        name="admin-plan-application-contact",
    ),
    path(
        "admin/plan-applications/<uuid:application_id>/close",
        AdminPlanApplicationCloseView.as_view(),
        name="admin-plan-application-close",
    ),
    path("plans", PublicPlanListView.as_view(), name="public-plan-list"),
    path("plans/<uuid:plan_id>", PublicPlanDetailView.as_view(), name="public-plan-detail"),
]
