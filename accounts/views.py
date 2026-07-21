from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.generic import TemplateView, UpdateView

from documents.delivery_services import email_configuration_status
from documents.stripe_services import stripe_configuration_status

from .forms import CompanySettingsForm
from .models import Company


class CompanySettingsView(LoginRequiredMixin, UpdateView):
    model = Company
    form_class = CompanySettingsForm
    template_name = "accounts/company_settings.html"

    def get_object(self, queryset=None):
        return self.request.user.company

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Company settings saved.")
        return response

    def get_success_url(self):
        return reverse("accounts:settings")


class IntegrationStatusView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/integration_status.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["email_status"] = email_configuration_status()
        context["stripe_status"] = stripe_configuration_status()
        return context
