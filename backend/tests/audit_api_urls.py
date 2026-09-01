from django.urls import include, path

urlpatterns = [
    path("api/v1/", include("apps.admin_rbac.urls")),
    path("api/v1/", include("apps.quotas.urls")),
]
