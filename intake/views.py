from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import FormView, ListView, UpdateView

from core.mixins import CompanyScopedQuerysetMixin

from .forms import (
    ClientFromNoteForm,
    ExistingClientFromNoteForm,
    NoteForm,
    ProjectFromNoteForm,
    QuickNoteForm,
)
from .models import Note


@login_required
@require_POST
def quick_add(request):
    form = QuickNoteForm(request.POST, company=request.user.company)
    if form.is_valid():
        form.save()
        request.session.pop("quick_note_draft", None)
        messages.success(request, "Note captured.")
    else:
        request.session["quick_note_draft"] = {
            name: request.POST.get(name, "") for name in form.fields
        }
        messages.error(request, "Review the highlighted Quick Note fields.")

    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse("intake:list")
    return redirect(next_url)


class NoteListView(LoginRequiredMixin, CompanyScopedQuerysetMixin, ListView):
    model = Note
    context_object_name = "notes"
    template_name = "intake/note_list.html"
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset().select_related("client", "project")
        if self.request.GET.get("archived") != "1":
            queryset = queryset.filter(is_archived=False)
        return queryset


class NoteUpdateView(
    LoginRequiredMixin,
    CompanyScopedQuerysetMixin,
    UpdateView,
):
    model = Note
    form_class = NoteForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "Edit note", "submit_label": "Save note"}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.request.user.company
        return kwargs

    def get_success_url(self):
        return reverse("intake:list")


@login_required
@require_POST
def toggle_archive(request, pk):
    note = get_object_or_404(Note.objects.for_company(request.user.company), pk=pk)
    note.is_archived = not note.is_archived
    note.save(update_fields=["is_archived", "updated_at"])
    messages.success(request, "Note archived." if note.is_archived else "Note restored.")
    return redirect("intake:list")


class CreateClientFromNoteView(LoginRequiredMixin, FormView):
    form_class = ClientFromNoteForm
    template_name = "intake/client_from_note.html"
    note = None

    def dispatch(self, request, *args, **kwargs):
        self.note = get_object_or_404(
            Note.objects.for_company(request.user.company).select_related("client", "project"),
            pk=kwargs["pk"],
        )
        if self.note.project_id:
            messages.info(request, "This note is already attached to a project.")
            return redirect("projects:detail", pk=self.note.project_id)
        if self.note.client_id:
            messages.info(request, "This note is already attached to a client.")
            return redirect("intake:create-project", pk=self.note.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(company=self.request.user.company, note=self.note)
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        initial.update(
            company_name=self.note.prospect_company_name,
            contact_first_name=self.note.contact_first_name,
            contact_last_name=self.note.contact_last_name,
        )
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["note"] = self.note
        context.setdefault(
            "existing_client_form",
            ExistingClientFromNoteForm(
                note=self.note,
                company=self.request.user.company,
            ),
        )
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get("conversion_action") == "use_existing":
            form = ExistingClientFromNoteForm(
                request.POST,
                note=self.note,
                company=request.user.company,
            )
            if form.is_valid():
                client = form.save()
                messages.success(request, f"Note attached to {client.display_name}.")
                if form.cleaned_data["create_project"]:
                    return redirect("intake:create-project", pk=self.note.pk)
                return redirect("clients:detail", pk=client.pk)
            return self.render_to_response(
                self.get_context_data(existing_client_form=form)
            )
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        client = form.save()
        messages.success(self.request, "Client created from note.")
        if form.cleaned_data["create_project"]:
            return redirect("intake:create-project", pk=self.note.pk)
        return redirect("clients:detail", pk=client.pk)


class CreateProjectFromNoteView(LoginRequiredMixin, FormView):
    form_class = ProjectFromNoteForm
    template_name = "shared/form.html"
    note = None

    def dispatch(self, request, *args, **kwargs):
        self.note = get_object_or_404(
            Note.objects.for_company(request.user.company).select_related("client", "project"),
            pk=kwargs["pk"],
        )
        if self.note.project_id:
            messages.info(request, "This note is already attached to a project.")
            return redirect("projects:detail", pk=self.note.project_id)
        if not self.note.client_id:
            messages.info(request, "Create or attach a client before creating a project.")
            return redirect("intake:create-client", pk=self.note.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        client = self.note.client
        initial.update(
            client=client.pk,
            description=self.note.body,
            address_1=client.billing_address_1,
            address_2=client.billing_address_2,
            city=client.billing_city,
            state=client.billing_state,
            postal_code=client.billing_postal_code,
        )
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(company=self.request.user.company, note=self.note)
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            page_title="Create project from note",
            submit_label="Create project",
        )
        return context

    def form_valid(self, form):
        project = form.save()
        messages.success(self.request, f"Project {project.number} created from note.")
        return redirect("projects:detail", pk=project.pk)
