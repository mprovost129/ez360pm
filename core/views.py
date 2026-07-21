from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import connection
from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, TemplateView

from documents.models import Document, Payment

from .dashboard import dashboard_context


class HomeView(LoginRequiredMixin, TemplateView):
    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(dashboard_context(self.request.user.company))
        return context


def _selected_month(value):
    if value:
        try:
            return date.fromisoformat(f"{value}-01")
        except ValueError:
            pass
    return timezone.localdate().replace(day=1)


class RevenueView(LoginRequiredMixin, ListView):
    model = Payment
    context_object_name = "payments"
    template_name = "core/revenue.html"
    paginate_by = 100
    month = None

    def get_queryset(self):
        self.month = _selected_month(self.request.GET.get("month"))
        month_end = self.month.replace(day=monthrange(self.month.year, self.month.month)[1])
        return Payment.objects.filter(
            document__company=self.request.user.company,
            received_at__range=(self.month, month_end),
        ).select_related("document", "document__project", "document__project__client")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["selected_month"] = self.month
        context["revenue_total"] = self.object_list.aggregate(value=Sum("amount"))[
            "value"
        ] or Decimal("0.00")
        context["method_totals"] = self.object_list.values("method").annotate(
            total=Sum("amount")
        )
        context["method_totals"] = [
            {
                "label": Payment.Method(row["method"]).label,
                "total": row["total"],
            }
            for row in context["method_totals"]
        ]
        context["previous_month"] = (self.month - timedelta(days=1)).replace(day=1)
        month_end = self.month.replace(day=monthrange(self.month.year, self.month.month)[1])
        context["next_month"] = (month_end + timedelta(days=1)).replace(day=1)
        return context


class DraftDocumentListView(LoginRequiredMixin, ListView):
    model = Document
    context_object_name = "documents"
    template_name = "core/draft_documents.html"

    def get_queryset(self):
        return Document.objects.for_company(self.request.user.company).filter(
            status=Document.Status.DRAFT
        ).select_related("project", "project__client")


class HealthView(View):
    """Minimal deployment health check including database connectivity."""

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception:
            return JsonResponse({"status": "unavailable"}, status=503)
        return JsonResponse({"status": "ok"})
