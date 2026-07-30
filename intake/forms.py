from django import forms
from django.db import transaction

from clients.forms import ClientCreateForm
from clients.models import Client
from core.forms import CompanyScopedModelForm
from projects.forms import ProjectForm
from projects.models import Project

from .models import Note
from .upload_security import validate_note_attachment


class QuickNoteForm(CompanyScopedModelForm):
    class Meta:
        model = Note
        fields = (
            "project",
            "activity_type",
            "source_type",
            "contact_first_name",
            "contact_last_name",
            "prospect_company_name",
            "source_email",
            "source_reference",
            "body",
        )
        labels = {
            "project": "Existing project (optional)",
            "activity_type": "Update type",
            "source_type": "Received by",
            "contact_first_name": "First name",
            "contact_last_name": "Last name",
            "prospect_company_name": "Company name",
            "source_email": "Sender email",
            "source_reference": "Email subject / source",
        }
        widgets = {
            "contact_first_name": forms.TextInput(
                attrs={"placeholder": "First name", "aria-label": "Customer first name"}
            ),
            "contact_last_name": forms.TextInput(
                attrs={"placeholder": "Last name", "aria-label": "Customer last name"}
            ),
            "prospect_company_name": forms.TextInput(
                attrs={"placeholder": "Company name", "aria-label": "Customer company name"}
            ),
            "source_email": forms.EmailInput(
                attrs={"placeholder": "Sender email", "aria-label": "Sender email"}
            ),
            "source_reference": forms.TextInput(
                attrs={"placeholder": "Email subject or source", "aria-label": "Source reference"}
            ),
            "body": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": "Paste the message or capture the update…",
                    "aria-label": "Quick note",
                }
            )
        }

    def __init__(self, *args, company=None, **kwargs):
        if args and args[0] is not None:
            data = args[0].copy()
            data.setdefault("activity_type", Note.ActivityType.GENERAL)
            data.setdefault("source_type", Note.SourceType.INTERNAL)
            args = (data, *args[1:])
        super().__init__(*args, company=company, **kwargs)
        project_queryset = (
            Project.objects.for_company(self.company)
            .select_related("client")
            .order_by("-updated_at", "number")
        )
        self.fields["project"].queryset = project_queryset if self.is_bound else project_queryset.none()
        self.fields["project"].empty_label = "No project — keep in intake"
        self.fields["project"].widget.attrs["data-quick-note-project"] = ""


class NoteForm(CompanyScopedModelForm):
    attachment = forms.FileField(
        required=False,
        validators=[validate_note_attachment],
        help_text="Optional email, PDF, Office document, text file, or image up to 20 MB.",
    )
    field_groups = (
        ("Activity", ("title", "activity_type", "status", "body", "follow_up_on")),
        (
            "Source",
            (
                "source_type",
                "contact_first_name",
                "contact_last_name",
                "prospect_company_name",
                "source_email",
                "source_reference",
                "original_content",
            ),
        ),
        ("Attach to", ("client", "project")),
        ("Files", ("attachment",)),
    )

    class Meta:
        model = Note
        fields = (
            "title",
            "activity_type",
            "status",
            "contact_first_name",
            "contact_last_name",
            "prospect_company_name",
            "source_type",
            "source_email",
            "source_reference",
            "body",
            "original_content",
            "follow_up_on",
            "client",
            "project",
        )
        labels = {
            "contact_first_name": "First name",
            "contact_last_name": "Last name",
            "prospect_company_name": "Company name",
        }
        widgets = {
            "body": forms.Textarea(attrs={"rows": 6}),
            "original_content": forms.Textarea(attrs={"rows": 10}),
            "follow_up_on": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, company=None, actor=None, **kwargs):
        self.actor = actor
        if args and args[0] is not None:
            data = args[0].copy()
            data.setdefault("activity_type", Note.ActivityType.GENERAL)
            data.setdefault("source_type", Note.SourceType.INTERNAL)
            data.setdefault("status", Note.Status.OPEN)
            args = (data, *args[1:])
        super().__init__(*args, company=company, **kwargs)
        self.fields["client"].queryset = Client.objects.for_company(
            self.company
        ).ordered_for_list()
        self.fields["project"].queryset = Project.objects.for_company(self.company)

    def clean(self):
        cleaned = super().clean()
        project = cleaned.get("project")
        client = cleaned.get("client")
        if project:
            if client and client.pk != project.client_id:
                self.add_error("client", "The selected client does not own this project.")
            cleaned["client"] = project.client
            self.instance.client = project.client
        return cleaned

    def save(self, commit=True):
        note = super().save(commit=False)
        note.mark_status(self.cleaned_data["status"], user=self.actor)
        if commit:
            note.save()
            self.save_m2m()
        return note


class ClientFromNoteForm(ClientCreateForm):
    create_project = forms.BooleanField(
        required=False,
        initial=True,
        label="Create a project next",
    )
    archive_note = forms.BooleanField(
        required=False,
        initial=True,
        label="Archive note after client-only conversion",
    )

    def __init__(self, *args, note, company=None, **kwargs):
        self.note = note
        super().__init__(*args, company=company, **kwargs)

    @transaction.atomic
    def save(self, commit=True):
        client = super().save(commit=commit)
        self.note.client = client
        self.note.project = None
        self.note.is_archived = (
            self.cleaned_data["archive_note"]
            and not self.cleaned_data["create_project"]
        )
        self.note.full_clean()
        self.note.save(update_fields=["client", "project", "is_archived", "updated_at"])
        return client


class ExistingClientFromNoteForm(forms.Form):
    client = forms.ModelChoiceField(
        queryset=Client.objects.none(),
        label="Existing client",
        help_text="Choose a match instead of creating a duplicate client.",
    )
    create_project = forms.BooleanField(
        required=False,
        initial=True,
        label="Create a project next",
    )
    archive_note = forms.BooleanField(
        required=False,
        initial=True,
        label="Archive note after client-only conversion",
    )

    def __init__(self, *args, note, company, **kwargs):
        self.note = note
        super().__init__(*args, **kwargs)
        clients = Client.objects.for_company(company).ordered_for_list()
        self.fields["client"].queryset = clients
        if not self.is_bound and note.prospect_company_name:
            match = clients.filter(company_name__iexact=note.prospect_company_name).first()
            if match:
                self.fields["client"].initial = match

    @transaction.atomic
    def save(self):
        client = self.cleaned_data["client"]
        self.note.client = client
        self.note.project = None
        self.note.is_archived = (
            self.cleaned_data["archive_note"]
            and not self.cleaned_data["create_project"]
        )
        self.note.full_clean()
        self.note.save(update_fields=["client", "project", "is_archived", "updated_at"])
        return client


class ProjectFromNoteForm(ProjectForm):
    archive_note = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, note, company=None, **kwargs):
        self.note = note
        initial = kwargs.setdefault("initial", {})
        initial.setdefault("client", note.client_id)
        super().__init__(*args, company=company, **kwargs)
        self.fields["client"].disabled = True

    @transaction.atomic
    def save(self, commit=True):
        project = super().save(commit=commit)
        self.note.client = project.client
        self.note.project = project
        self.note.is_archived = self.cleaned_data["archive_note"]
        self.note.full_clean()
        self.note.save(update_fields=["client", "project", "is_archived", "updated_at"])
        return project
