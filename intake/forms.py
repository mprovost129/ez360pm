from django import forms
from django.db import transaction

from clients.forms import ClientCreateForm
from clients.models import Client
from core.forms import CompanyScopedModelForm
from projects.forms import ProjectForm
from projects.models import Project

from .models import Note


class QuickNoteForm(CompanyScopedModelForm):
    class Meta:
        model = Note
        fields = (
            "contact_first_name",
            "contact_last_name",
            "prospect_company_name",
            "body",
        )
        labels = {
            "contact_first_name": "First name",
            "contact_last_name": "Last name",
            "prospect_company_name": "Company name",
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
            "body": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "What are they calling about?",
                    "aria-label": "Quick note",
                }
            )
        }


class NoteForm(CompanyScopedModelForm):
    class Meta:
        model = Note
        fields = (
            "contact_first_name",
            "contact_last_name",
            "prospect_company_name",
            "body",
            "client",
            "project",
        )
        labels = {
            "contact_first_name": "First name",
            "contact_last_name": "Last name",
            "prospect_company_name": "Company name",
        }
        widgets = {"body": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, company=None, **kwargs):
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
