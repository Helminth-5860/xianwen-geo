from django.urls import path

from .views import (
    AdminQuotaAccountListView,
    AdminQuotaAdjustmentView,
    AdminQuotaLedgerListView,
    CurrentQuotaAccountsView,
    UserQuotaLedgerView,
)

urlpatterns = [
    path("quotas", CurrentQuotaAccountsView.as_view(), name="current-quotas"),
    path("quota-ledger", UserQuotaLedgerView.as_view(), name="user-quota-ledger"),
    path("admin/quota-accounts", AdminQuotaAccountListView.as_view(), name="admin-quota-accounts"),
    path("admin/quota-ledger", AdminQuotaLedgerListView.as_view(), name="admin-quota-ledger"),
    path(
        "admin/quota-accounts/<uuid:account_id>/adjust/<str:action>",
        AdminQuotaAdjustmentView.as_view(),
        name="admin-quota-adjustment",
    ),
]
