from django.urls import path

from . import delivery_views, views
from .models import Document

app_name = "documents"

urlpatterns = [
    path("", views.InvoiceListView.as_view(), name="invoice-list"),
    path("new/", views.InvoiceCreateView.as_view(), name="invoice-create"),
    path("<int:pk>/", views.InvoiceDetailView.as_view(), name="invoice-detail"),
    path("<int:pk>/edit/", views.InvoiceUpdateView.as_view(), name="invoice-update"),
    path("<int:pk>/delete/", views.InvoiceDeleteView.as_view(), name="invoice-delete"),
    path("<int:pk>/issue/", views.invoice_issue, name="invoice-issue"),
    path(
        "<int:pk>/send/",
        delivery_views.DocumentSendView.as_view(
            doc_type=Document.Type.INVOICE,
            success_url_name="documents:invoice-detail",
        ),
        name="invoice-send",
    ),
    path("<int:pk>/void/", views.InvoiceVoidView.as_view(), name="invoice-void"),
    path("<int:pk>/release-time/", views.ReleaseVoidTimeView.as_view(), name="invoice-release-time"),
    path("<int:pk>/pdf/", views.InvoicePdfView.as_view(), name="invoice-pdf"),
    path("<int:pk>/attach-time/", views.AttachTimeView.as_view(), name="invoice-attach-time"),
    path("<int:invoice_pk>/lines/new/", views.LineItemCreateView.as_view(), name="line-create"),
    path("<int:invoice_pk>/lines/<int:line_pk>/edit/", views.LineItemUpdateView.as_view(), name="line-update"),
    path("<int:invoice_pk>/lines/<int:line_pk>/delete/", views.LineItemDeleteView.as_view(), name="line-delete"),
    path("<int:invoice_pk>/payments/new/", views.PaymentCreateView.as_view(), name="payment-create"),
    path("<int:invoice_pk>/payments/<int:payment_pk>/edit/", views.PaymentUpdateView.as_view(), name="payment-update"),
    path("<int:invoice_pk>/payments/<int:payment_pk>/delete/", views.PaymentDeleteView.as_view(), name="payment-delete"),
    path("<int:invoice_pk>/credits/new/", views.InvoiceCreditCreateView.as_view(), name="credit-create"),
    path("<int:invoice_pk>/credits/<int:credit_pk>/delete/", views.InvoiceCreditDeleteView.as_view(), name="credit-delete"),
]
