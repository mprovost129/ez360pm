from django.urls import path

from . import public_views, stripe_views

app_name = "public-documents"

urlpatterns = [
    path("<uuid:token>/", public_views.PublicDocumentView.as_view(), name="view"),
    path("<uuid:token>/accept/", public_views.public_proposal_accept, name="accept"),
    path("<uuid:token>/decline/", public_views.public_proposal_decline, name="decline"),
    path("<uuid:token>/checkout/", stripe_views.PublicCheckoutView.as_view(), name="checkout"),
    path("<uuid:token>/pdf/", public_views.PublicDocumentPdfView.as_view(), name="pdf"),
]
