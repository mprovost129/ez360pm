from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, FormView, ListView, UpdateView

from core.mixins import CompanyScopedQuerysetMixin

from .models import TimeEntry
from .time_forms import TimeEntryForm, TimeFilterForm, TimerStartForm
from .time_services import (
    TimerAlreadyRunning,
    delete_manual_entry,
    start_timer,
    stop_timer,
)


def _safe_next(request, fallback="projects:time-list"):
    next_url = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return reverse(fallback)


class TimeEntryListView(LoginRequiredMixin, CompanyScopedQuerysetMixin, ListView):
    model = TimeEntry
    context_object_name = "time_entries"
    template_name = "projects/timeentry_list.html"
    paginate_by = 50
    filter_form = None

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .filter(user=self.request.user)
            .select_related("project")
        )
        self.filter_form = TimeFilterForm(
            self.request.GET or None,
            company=self.request.user.company,
        )
        if self.filter_form.is_valid():
            project = self.filter_form.cleaned_data.get("project")
            date_from = self.filter_form.cleaned_data.get("date_from")
            date_to = self.filter_form.cleaned_data.get("date_to")
            unbilled = self.filter_form.cleaned_data.get("unbilled")
            if project:
                queryset = queryset.filter(project=project)
            if date_from:
                queryset = queryset.filter(start_time__date__gte=date_from)
            if date_to:
                queryset = queryset.filter(start_time__date__lte=date_to)
            if unbilled:
                queryset = queryset.filter(
                    end_time__isnull=False,
                    billable=True,
                    status=TimeEntry.Status.LOGGED,
                    line_item__isnull=True,
                )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        return context


class TimerStartView(LoginRequiredMixin, FormView):
    form_class = TimerStartForm
    template_name = "projects/timer_start.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.request.user.company
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        if self.request.GET.get("project"):
            initial["project"] = self.request.GET["project"]
        return initial

    def form_valid(self, form):
        try:
            start_timer(
                user=self.request.user,
                project=form.cleaned_data["project"],
                description=form.cleaned_data["description"],
                billable=form.cleaned_data["billable"],
            )
        except (TimerAlreadyRunning, ValidationError) as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)
        messages.success(self.request, "Timer started.")
        return redirect("projects:time-list")


@login_required
@require_POST
def timer_stop(request):
    try:
        entry = stop_timer(user=request.user)
    except ValidationError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, f"Timer stopped for {entry.project.number}.")
    return redirect(_safe_next(request))


class TimeEntryFormMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(company=self.request.user.company, user=self.request.user)
        return kwargs

    def get_success_url(self):
        return reverse("projects:time-list")


class TimeEntryCreateView(LoginRequiredMixin, TimeEntryFormMixin, CreateView):
    model = TimeEntry
    form_class = TimeEntryForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "Add time entry", "submit_label": "Save time"}

    def get_initial(self):
        initial = super().get_initial()
        if self.request.GET.get("project"):
            initial["project"] = self.request.GET["project"]
        return initial


class TimeEntryUpdateView(
    LoginRequiredMixin,
    CompanyScopedQuerysetMixin,
    TimeEntryFormMixin,
    UpdateView,
):
    model = TimeEntry
    form_class = TimeEntryForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "Edit time entry", "submit_label": "Save time"}

    def get_queryset(self):
        return super().get_queryset().filter(
            user=self.request.user,
            status=TimeEntry.Status.LOGGED,
            end_time__isnull=False,
        )


class TimeEntryDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        entry = get_object_or_404(
            TimeEntry.objects.filter(company=request.user.company, user=request.user),
            pk=pk,
        )
        try:
            delete_manual_entry(user=request.user, entry=entry)
        except ValidationError as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, "Time entry deleted.")
        return redirect("projects:time-list")
