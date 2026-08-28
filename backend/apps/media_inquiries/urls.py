from django.urls import path

from .views import (
    AdminPaidMediaInquiryDetailView,
    AdminPaidMediaInquiryListView,
    PaidMediaCatalogView,
    PaidMediaInquiryCancelView,
    SubjectPaidMediaInquiryListCreateView,
)

urlpatterns = [
    path("paid-media-catalog", PaidMediaCatalogView.as_view(), name="paid-media-catalog"),
    path(
        "subjects/<uuid:subject_id>/paid-media-inquiries",
        SubjectPaidMediaInquiryListCreateView.as_view(),
        name="subject-paid-media-inquiries",
    ),
    path(
        "subjects/<uuid:subject_id>/paid-media-inquiries/<uuid:inquiry_id>",
        PaidMediaInquiryCancelView.as_view(),
        name="subject-paid-media-inquiry-cancel",
    ),
    path(
        "paid-media-inquiries/<uuid:inquiry_id>",
        PaidMediaInquiryCancelView.as_view(),
        name="paid-media-inquiry-cancel",
    ),
    path(
        "admin/paid-media-inquiries",
        AdminPaidMediaInquiryListView.as_view(),
        name="admin-paid-media-inquiries",
    ),
    path(
        "admin/paid-media-inquiries/<uuid:inquiry_id>",
        AdminPaidMediaInquiryDetailView.as_view(),
        name="admin-paid-media-inquiry-detail",
    ),
]
