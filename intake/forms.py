from django import forms
from django.db import transaction

from clients.forms import ClientCreateForm
from clients.models import Client
from core.forms import CompanyScopedModelForm
from projects.models import Project

from .models import Note


class QuickNoteForm(CompanyScopedModelForm):
    class Meta:
        model = Note
        fields = ("body",)
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Capture a call, email, text, or reminder...",
                    "aria-label": "Quick note",
                }
            )
        }


class NoteForm(CompanyScopedModelForm):
    class Meta:
        model = Note
        fields = ("body", "project", "client")
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
    archive_note = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, note, company=None, **kwargs):
        self.note = note
        super().__init__(*args, company=company, **kwargs)

    @transaction.atomic
    def save(self, commit=True):
        client = super().save(commit=commit)
        self.note.client = client
        self.note.project = None
        self.note.is_archived = self.cleaned_data["archive_note"]
        self.note.full_clean()
        self.note.save(update_fields=["client", "project", "is_archived", "updated_at"])
        return client

