from django.urls import path

from .resend_views import resend_webhook
from .stripe_views import stripe_webhook

app_name = "webhooks"

urlpatterns = [
    path("stripe/", stripe_webhook, name="stripe"),
    path("resend/", resend_webhook, name="resend"),
]
