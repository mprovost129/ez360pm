from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import connection
from django.http import JsonResponse
from django.views import View
from django.views.generic import TemplateView


class HomeView(LoginRequiredMixin, TemplateView):
    template_name = 'core/home.html'

    def get_context_data(self, **kwargs):
        from intake.models import Note
        from projects.models import Project

        context = super().get_context_data(**kwargs)
        company = self.request.user.company
        context["recent_notes"] = Note.objects.for_company(company).filter(
            is_archived=False
        )[:5]
        context["lead_projects"] = Project.objects.for_company(company).filter(
            status=Project.Status.LEAD
        ).select_related("client").prefetch_related("client__contacts")[:8]
        return context


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
