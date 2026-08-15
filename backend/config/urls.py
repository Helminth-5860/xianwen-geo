from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/", include("apps.users.urls")),
    path("api/v1/", include("apps.admin_rbac.urls")),
    path("api/v1/", include("apps.plans.urls")),
    path("api/v1/", include("apps.quotas.urls")),
    path("api/v1/", include("apps.subjects.urls")),
    path("api/v1/", include("apps.keywords.urls")),
    path("api/v1/", include("apps.documents.urls")),
    path("api/v1/", include("apps.web_sources.urls")),
]

handler404 = "apps.core.handlers.api_page_not_found"
handler500 = "apps.core.handlers.api_server_error"
