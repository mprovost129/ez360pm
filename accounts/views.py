from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from documents.delivery_services import email_configuration_status
from documents.stripe_services import stripe_configuration_status


class IntegrationStatusView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/integration_status.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["email_status"] = email_configuration_status()
        context["stripe_status"] = stripe_configuration_status()
        return context
