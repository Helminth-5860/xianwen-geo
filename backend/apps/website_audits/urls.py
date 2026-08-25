from django.urls import path

from .views import SubjectWebsiteAuditListView, WebsiteAuditCreateView, WebsiteAuditDetailView

urlpatterns = [
    path(
        "subjects/<uuid:subject_id>/website-audits",
        WebsiteAuditCreateView.as_view(),
        name="website-audit-create",
    ),
    path(
        "subjects/<uuid:subject_id>/website-audits/history",
        SubjectWebsiteAuditListView.as_view(),
        name="website-audit-history",
    ),
    path(
        "website-audits/<uuid:audit_id>",
        WebsiteAuditDetailView.as_view(),
        name="website-audit-detail",
    ),
]
