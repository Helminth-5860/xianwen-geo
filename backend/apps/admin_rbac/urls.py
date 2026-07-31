from django.urls import path

from .views import (
    AdminDetailView,
    AdminListCreateView,
    AdminMeView,
    CustomerAssignmentView,
    PermissionListView,
    RoleDetailView,
    RoleDisableView,
    RoleListCreateView,
    status_view,
)

urlpatterns = [
    path("admin/me", AdminMeView.as_view(), name="admin-me"),
    path("admin/admins", AdminListCreateView.as_view(), name="admin-list"),
    path("admin/admins/<uuid:profile_id>", AdminDetailView.as_view(), name="admin-detail"),
    path(
        "admin/admins/<uuid:profile_id>/disable",
        status_view("disable").as_view(),
        name="admin-disable",
    ),
    path(
        "admin/admins/<uuid:profile_id>/enable",
        status_view("enable").as_view(),
        name="admin-enable",
    ),
    path(
        "admin/admins/<uuid:profile_id>/lock",
        status_view("lock").as_view(),
        name="admin-lock",
    ),
    path(
        "admin/admins/<uuid:profile_id>/unlock",
        status_view("unlock").as_view(),
        name="admin-unlock",
    ),
    path("admin/roles", RoleListCreateView.as_view(), name="role-list"),
    path("admin/roles/<uuid:role_id>", RoleDetailView.as_view(), name="role-detail"),
    path(
        "admin/roles/<uuid:role_id>/disable",
        RoleDisableView.as_view(),
        name="role-disable",
    ),
    path("admin/permissions", PermissionListView.as_view(), name="permission-list"),
    path(
        "admin/users/<uuid:customer_id>/assignment",
        CustomerAssignmentView.as_view(),
        name="customer-assignment",
    ),
]
