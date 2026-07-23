from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from core.mixins import CompanyScopedQuerysetMixin

from .forms import ProjectForm
from .models import Project
from .workflow import complete_paid_project, start_without_retainer


class CompanyFormMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.request.user.company
        return kwargs


class ProjectListView(LoginRequiredMixin, CompanyScopedQuerysetMixin, ListView):
    model = Project
    context_object_name = "projects"
    template_name = "projects/project_list.html"
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset()
        status = self.request.GET.get("status")
        if status in Project.Status.values:
            queryset = queryset.filter(status=status)
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(number__icontains=query)
                | Q(name__icontains=query)
                | Q(client__company_name__icontains=query)
                | Q(client__contacts__first_name__icontains=query)
                | Q(client__contacts__last_name__icontains=query)
                | Q(address_1__icontains=query)
                | Q(municipality__icontains=query)
                | Q(parcel_id__icontains=query)
            ).distinct()
        return queryset.select_related("client").prefetch_related("client__contacts")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["selected_status"] = self.request.GET.get("status", "")
        context["status_choices"] = Project.Status.choices
        return context


class ProjectDetailView(LoginRequiredMixin, CompanyScopedQuerysetMixin, DetailView):
    model = Project
    context_object_name = "project"
    template_name = "projects/project_detail.html"

    def get_queryset(self):
        return super().get_queryset().select_related("client").prefetch_related(
            "client__contacts",
            "documents",
            "notes",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["recent_time_entries"] = self.object.time_entries.filter(
            user=self.request.user
        )[:10]
        context["can_start_without_retainer"] = (
            self.object.status == Project.Status.APPROVED
            and not self.object.documents.filter(
                doc_type="invoice",
                invoice_kind="retainer",
            ).exclude(status="void").exists()
        )
        context["can_complete"] = (
            self.object.status in {Project.Status.ACTIVE, Project.Status.ON_HOLD}
            and self.object.documents.filter(
                doc_type="invoice",
                invoice_kind="final",
                status="paid",
            ).exists()
        )
        return context


class ProjectCreateView(LoginRequiredMixin, CompanyFormMixin, CreateView):
    model = Project
    form_class = ProjectForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "New project", "submit_label": "Create project"}

    def get_initial(self):
        initial = super().get_initial()
        client_id = self.request.GET.get("client")
        if client_id:
            initial["client"] = client_id
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Project {self.object.number} created.")
        return response

    def get_success_url(self):
        return reverse("projects:detail", args=(self.object.pk,))


class ProjectUpdateView(
    LoginRequiredMixin,
    CompanyScopedQuerysetMixin,
    CompanyFormMixin,
    UpdateView,
):
    model = Project
    form_class = ProjectForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "Edit project", "submit_label": "Save project"}

    def get_success_url(self):
        return reverse("projects:detail", args=(self.object.pk,))


class ProjectDeleteView(LoginRequiredMixin, CompanyScopedQuerysetMixin, DeleteView):
    model = Project
    template_name = "shared/confirm_delete.html"
    success_url = reverse_lazy("projects:list")
    extra_context = {
        "page_title": "Delete project",
        "warning": "Only unused lead projects should be deleted.",
    }

    def form_valid(self, form):
        if self.object.status != Project.Status.LEAD:
            messages.error(self.request, "Only lead projects can be deleted.")
            return redirect("projects:detail", pk=self.object.pk)
        try:
            self.object.delete()
        except ProtectedError:
            messages.error(self.request, "This project has attached history and cannot be deleted.")
            return redirect("projects:detail", pk=self.object.pk)
        messages.success(self.request, "Project deleted.")
        return redirect(self.success_url)


def scoped_project(request, pk):
    return get_object_or_404(Project.objects.for_company(request.user.company), pk=pk)


@login_required
@require_POST
def project_start_without_retainer(request, pk):
    try:
        project = scoped_project(request, pk)
        start_without_retainer(project=project)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(request, "Project started without a retainer.")
    return redirect("projects:detail", pk=pk)


@login_required
@require_POST
def project_complete(request, pk):
    try:
        project = scoped_project(request, pk)
        complete_paid_project(project=project)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(request, "Project marked complete.")
    return redirect("projects:detail", pk=pk)
