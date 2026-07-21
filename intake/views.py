from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import FormView, ListView, UpdateView

from core.mixins import CompanyScopedQuerysetMixin

from .forms import ClientFromNoteForm, NoteForm, QuickNoteForm
from .models import Note


@login_required
@require_POST
def quick_add(request):
    form = QuickNoteForm(request.POST, company=request.user.company)
    if form.is_valid():
        form.save()
        messages.success(request, "Note captured.")
    else:
        messages.error(request, "Enter note text before saving.")

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
            Note.objects.for_company(request.user.company),
            pk=kwargs["pk"],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(company=self.request.user.company, note=self.note)
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["note"] = self.note
        return context

    def form_valid(self, form):
        client = form.save()
        messages.success(self.request, "Client created from note.")
        return redirect("clients:detail", pk=client.pk)

