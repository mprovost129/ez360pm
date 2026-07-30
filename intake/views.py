from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from core.mixins import CompanyScopedQuerysetMixin
from projects.models import Project

from .forms import (
    ActivityItemForm,
    ClientFromNoteForm,
    ExistingClientFromNoteForm,
    NoteForm,
    ProjectFromNoteForm,
    QuickNoteForm,
)
from .models import ActivityEvent, ActivityItem, Note, NoteAttachment
from .services import add_note_attachment, create_activity_item, record_activity_event


@login_required
def project_options(request):
    projects = (
        Project.objects.for_company(request.user.company)
        .select_related("client")
        .order_by("-updated_at", "number")[:200]
    )
    return JsonResponse(
        {
            "projects": [
                {"id": project.pk, "label": str(project)} for project in projects
            ]
        }
    )


@login_required
@require_POST
def quick_add(request):
    form = QuickNoteForm(request.POST, company=request.user.company)
    if form.is_valid():
        note = form.save(commit=False)
        note.created_by = request.user
        note.title = note.source_reference or next(
            (line.strip() for line in note.body.splitlines() if line.strip()),
            "",
        )[:255]
        if note.source_type == Note.SourceType.EMAIL:
            note.original_content = note.body
        if note.activity_type == Note.ActivityType.CLIENT_CHANGE:
            note.status = Note.Status.ACTION_REQUIRED
        note.save()
        record_activity_event(
            note=note,
            event_type=ActivityEvent.Type.CREATED,
            description="Project activity captured from Quick Notes.",
            actor=request.user,
            metadata={"source": note.source_type, "activity_type": note.activity_type},
        )
        request.session.pop("quick_note_draft", None)
        messages.success(
            request,
            "Project update captured." if note.project_id else "Note captured.",
        )
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
        queryset = super().get_queryset().select_related("client", "project", "created_by")
        show_archived = self.request.GET.get("archived") == "1"
        queryset = queryset.filter(is_archived=show_archived)
        status = self.request.GET.get("status", "")
        if status in Note.Status.values:
            queryset = queryset.filter(status=status)
        activity_type = self.request.GET.get("type", "")
        if activity_type in Note.ActivityType.values:
            queryset = queryset.filter(activity_type=activity_type)
        project_id = self.request.GET.get("project", "")
        if project_id.isdigit():
            queryset = queryset.filter(project_id=project_id)
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(title__icontains=query)
                | Q(body__icontains=query)
                | Q(original_content__icontains=query)
                | Q(source_reference__icontains=query)
                | Q(contact_first_name__icontains=query)
                | Q(contact_last_name__icontains=query)
                | Q(project__number__icontains=query)
                | Q(project__name__icontains=query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            status_choices=Note.Status.choices,
            activity_type_choices=Note.ActivityType.choices,
            projects=Project.objects.for_company(self.request.user.company).order_by(
                "-updated_at", "number"
            ),
            selected_status=self.request.GET.get("status", ""),
            selected_type=self.request.GET.get("type", ""),
            selected_project=self.request.GET.get("project", ""),
            search_query=self.request.GET.get("q", ""),
        )
        return context


class NoteFormViewMixin:
    form_class = NoteForm
    template_name = "intake/note_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(company=self.request.user.company, actor=self.request.user)
        return kwargs

    def form_valid(self, form):
        is_new = not form.instance.pk
        previous_status = form.initial.get("status")
        changed_fields = [field for field in form.changed_data if field != "attachment"]
        if is_new:
            form.instance.created_by = self.request.user
        response = super().form_valid(form)
        if is_new:
            record_activity_event(
                note=self.object,
                event_type=ActivityEvent.Type.CREATED,
                description="Project activity created.",
                actor=self.request.user,
                metadata={
                    "source": self.object.source_type,
                    "activity_type": self.object.activity_type,
                },
            )
        elif changed_fields:
            record_activity_event(
                note=self.object,
                event_type=ActivityEvent.Type.UPDATED,
                description="Project activity updated.",
                actor=self.request.user,
                metadata={"fields": changed_fields},
            )
            if "status" in changed_fields:
                record_activity_event(
                    note=self.object,
                    event_type=ActivityEvent.Type.STATUS_CHANGED,
                    description=(
                        f"Activity status changed from {previous_status or 'unknown'} "
                        f"to {self.object.status}."
                    ),
                    actor=self.request.user,
                    metadata={"from": previous_status, "to": self.object.status},
                )
        uploaded_file = form.cleaned_data.get("attachment")
        if uploaded_file:
            add_note_attachment(
                note=self.object,
                uploaded_file=uploaded_file,
                uploaded_by=self.request.user,
            )
        messages.success(self.request, "Project activity saved.")
        return response

    def get_success_url(self):
        return reverse("intake:detail", args=(self.object.pk,))


class NoteCreateView(LoginRequiredMixin, NoteFormViewMixin, CreateView):
    model = Note
    extra_context = {"page_title": "New project activity", "submit_label": "Save activity"}

    def get_initial(self):
        initial = super().get_initial()
        project_id = self.request.GET.get("project")
        if project_id:
            project = Project.objects.for_company(self.request.user.company).filter(pk=project_id).first()
            if project:
                initial.update(project=project, client=project.client)
        return initial


class NoteDetailView(LoginRequiredMixin, CompanyScopedQuerysetMixin, DetailView):
    model = Note
    context_object_name = "note"
    template_name = "intake/note_detail.html"

    def get_queryset(self):
        return super().get_queryset().select_related(
            "client", "project", "created_by", "resolved_by"
        ).prefetch_related(
            "attachments",
            "action_items__created_by",
            "action_items__resolved_by",
            "events__actor",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("item_form", ActivityItemForm(actor=self.request.user))
        context["today"] = timezone.localdate()
        return context


class NoteUpdateView(
    LoginRequiredMixin,
    CompanyScopedQuerysetMixin,
    NoteFormViewMixin,
    UpdateView,
):
    model = Note
    extra_context = {"page_title": "Edit project activity", "submit_label": "Save activity"}


@login_required
@require_POST
def add_activity_item(request, pk):
    note = get_object_or_404(
        Note.objects.for_company(request.user.company).prefetch_related(
            "attachments", "action_items"
        ),
        pk=pk,
    )
    form = ActivityItemForm(request.POST, actor=request.user)
    if form.is_valid():
        create_activity_item(
            note=note,
            data={field: form.cleaned_data[field] for field in form.Meta.fields},
            created_by=request.user,
        )
        messages.success(request, "Action item added.")
        return redirect(f"{reverse('intake:detail', args=(note.pk,))}#action-items")
    return render(
        request,
        "intake/note_detail.html",
        {"note": note, "item_form": form, "today": timezone.localdate()},
        status=400,
    )


class ActivityItemUpdateView(LoginRequiredMixin, UpdateView):
    model = ActivityItem
    form_class = ActivityItemForm
    template_name = "shared/form.html"
    pk_url_kwarg = "item_pk"
    extra_context = {"page_title": "Edit action item", "submit_label": "Save item"}

    def get_queryset(self):
        return ActivityItem.objects.filter(
            note_id=self.kwargs["pk"],
            note__company=self.request.user.company,
        ).select_related("note")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        return kwargs

    def get_success_url(self):
        return f"{reverse('intake:detail', args=(self.object.note_id,))}#action-items"

    def form_valid(self, form):
        previous_status = form.initial.get("status")
        changed_fields = list(form.changed_data)
        response = super().form_valid(form)
        if changed_fields:
            record_activity_event(
                note=self.object.note,
                event_type=ActivityEvent.Type.ITEM_UPDATED,
                description=f"Action item updated: {self.object.title}",
                actor=self.request.user,
                metadata={"item_id": self.object.pk, "fields": changed_fields},
            )
            if "status" in changed_fields:
                record_activity_event(
                    note=self.object.note,
                    event_type=ActivityEvent.Type.ITEM_STATUS_CHANGED,
                    description=(
                        f"Action item status changed from {previous_status or 'unknown'} "
                        f"to {self.object.status}: {self.object.title}"
                    ),
                    actor=self.request.user,
                    metadata={
                        "item_id": self.object.pk,
                        "from": previous_status,
                        "to": self.object.status,
                    },
                )
        return response


@login_required
@require_POST
def update_activity_item_status(request, pk, item_pk, status):
    item = get_object_or_404(
        ActivityItem.objects.select_related("note"),
        pk=item_pk,
        note_id=pk,
        note__company=request.user.company,
    )
    if status not in ActivityItem.Status.values:
        raise Http404
    item.mark_status(status, user=request.user)
    item.full_clean()
    item.save(update_fields=["status", "resolved_at", "resolved_by", "updated_at"])
    record_activity_event(
        note=item.note,
        event_type=ActivityEvent.Type.ITEM_STATUS_CHANGED,
        description=f"Action item marked {item.get_status_display().lower()}: {item.title}",
        actor=request.user,
        metadata={"item_id": item.pk, "to": item.status},
    )
    messages.success(request, f"Action item marked {item.get_status_display().lower()}.")
    return redirect(f"{reverse('intake:detail', args=(pk,))}#action-items")


@login_required
@require_POST
def update_status(request, pk, status):
    note = get_object_or_404(Note.objects.for_company(request.user.company), pk=pk)
    if status not in Note.Status.values:
        raise Http404
    note.mark_status(status, user=request.user)
    note.full_clean()
    note.save(update_fields=["status", "resolved_at", "resolved_by", "updated_at"])
    record_activity_event(
        note=note,
        event_type=ActivityEvent.Type.STATUS_CHANGED,
        description=f"Activity marked {note.get_status_display().lower()}.",
        actor=request.user,
        metadata={"to": note.status},
    )
    messages.success(request, f"Activity marked {note.get_status_display().lower()}.")
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse("intake:detail", args=(note.pk,))
    return redirect(next_url)


class NoteAttachmentDownloadView(LoginRequiredMixin, DetailView):
    model = NoteAttachment

    def get_queryset(self):
        return NoteAttachment.objects.filter(note__company=self.request.user.company)

    def get(self, request, *args, **kwargs):
        attachment = self.get_object()
        try:
            file_handle = attachment.file.open("rb")
        except (FileNotFoundError, OSError):
            raise Http404 from None
        response = FileResponse(
            file_handle,
            as_attachment=True,
            filename=attachment.original_name,
            content_type=attachment.content_type or "application/octet-stream",
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response


@login_required
@require_POST
def delete_attachment(request, pk, attachment_pk):
    attachment = get_object_or_404(
        NoteAttachment.objects.filter(note__company=request.user.company),
        pk=attachment_pk,
        note_id=pk,
    )
    original_name = attachment.original_name
    record_activity_event(
        note=attachment.note,
        event_type=ActivityEvent.Type.ATTACHMENT_REMOVED,
        description=f"Attachment removed: {original_name}",
        actor=request.user,
        metadata={"file_name": original_name},
    )
    attachment.delete()
    messages.success(request, "Attachment removed.")
    return redirect("intake:detail", pk=pk)


@login_required
@require_POST
def toggle_archive(request, pk):
    note = get_object_or_404(Note.objects.for_company(request.user.company), pk=pk)
    note.is_archived = not note.is_archived
    note.save(update_fields=["is_archived", "updated_at"])
    record_activity_event(
        note=note,
        event_type=ActivityEvent.Type.UPDATED,
        description="Activity archived." if note.is_archived else "Activity restored.",
        actor=request.user,
        metadata={"fields": ["is_archived"], "archived": note.is_archived},
    )
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
                record_activity_event(
                    note=self.note,
                    event_type=ActivityEvent.Type.UPDATED,
                    description=f"Activity attached to client: {client.display_name}",
                    actor=request.user,
                    metadata={"fields": ["client"], "client_id": client.pk},
                )
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
        record_activity_event(
            note=self.note,
            event_type=ActivityEvent.Type.UPDATED,
            description=f"Client created and attached: {client.display_name}",
            actor=self.request.user,
            metadata={"fields": ["client"], "client_id": client.pk},
        )
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
        record_activity_event(
            note=self.note,
            event_type=ActivityEvent.Type.UPDATED,
            description=f"Project created and attached: {project.number}",
            actor=self.request.user,
            metadata={"fields": ["project"], "project_id": project.pk},
        )
        messages.success(self.request, f"Project {project.number} created from note.")
        return redirect("projects:detail", pk=project.pk)
