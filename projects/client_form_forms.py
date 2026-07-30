from pathlib import Path

from django import forms

from .models import (
    ClientFormQuestion,
    ClientFormTemplate,
    ProjectClientForm,
    ProjectFormAnswer,
    ProjectFormUpload,
)

MAX_CLIENT_FORM_UPLOAD_BYTES = 10 * 1024 * 1024
CLIENT_FORM_UPLOAD_EXTENSIONS = {
    ".doc",
    ".docx",
    ".heic",
    ".heif",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".webp",
}
CLIENT_FORM_UPLOAD_CONTENT_TYPES = {
    "application/msword",
    "application/octet-stream",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/heic",
    "image/heif",
    "image/jpeg",
    "image/png",
    "image/webp",
}


def validate_client_form_upload(uploaded_file):
    if uploaded_file.size > MAX_CLIENT_FORM_UPLOAD_BYTES:
        raise forms.ValidationError("Files must be 10 MB or smaller.")
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix not in CLIENT_FORM_UPLOAD_EXTENSIONS:
        raise forms.ValidationError(
            "Upload a PDF, Word document, JPEG, PNG, WebP, HEIC, or HEIF file."
        )
    content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    if content_type and content_type not in CLIENT_FORM_UPLOAD_CONTENT_TYPES:
        raise forms.ValidationError("The reported file type is not allowed.")


class ClientFormTemplateForm(forms.ModelForm):
    class Meta:
        model = ClientFormTemplate
        fields = ("name", "description", "welcome_message", "estimated_minutes", "is_active")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "welcome_message": forms.Textarea(attrs={"rows": 5}),
        }
        help_texts = {
            "description": "Internal description used when selecting a form.",
            "welcome_message": "Shown to the client above the questions.",
            "is_active": "Inactive templates remain in history but cannot be selected for new forms.",
        }


class ClientFormQuestionForm(forms.ModelForm):
    options_text = forms.CharField(
        required=False,
        label="Options",
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="For dropdowns and checkboxes, enter one option per line.",
    )

    class Meta:
        model = ClientFormQuestion
        fields = ("section", "label", "help_text", "field_type", "required")
        widgets = {"help_text": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["options_text"].initial = "\n".join(self.instance.options or [])

    def clean(self):
        cleaned = super().clean()
        field_type = cleaned.get("field_type")
        options = [line.strip() for line in cleaned.get("options_text", "").splitlines() if line.strip()]
        if field_type in {
            ClientFormQuestion.FieldType.SELECT,
            ClientFormQuestion.FieldType.MULTI_SELECT,
        } and not options:
            self.add_error("options_text", "Add at least one option for this input type.")
        if field_type not in {
            ClientFormQuestion.FieldType.SELECT,
            ClientFormQuestion.FieldType.MULTI_SELECT,
        }:
            options = []
        self.instance.options = options
        cleaned["options"] = options
        return cleaned

    def save(self, commit=True):
        self.instance.options = self.cleaned_data["options"]
        return super().save(commit=commit)


class ProjectClientFormSendForm(forms.Form):
    template = forms.ModelChoiceField(queryset=ClientFormTemplate.objects.none())
    recipient_name = forms.CharField(max_length=255)
    recipient_email = forms.EmailField()
    email_subject = forms.CharField(max_length=255, required=False)
    email_message = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))

    def __init__(self, *args, company, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["template"].queryset = ClientFormTemplate.objects.for_company(company).filter(
            is_active=True
        )
        self.fields["email_subject"].help_text = "Leave blank to use a branded default subject."
        self.fields["email_message"].help_text = "Optional note included above the form link."
        contact = project.client.primary_contact
        if not self.is_bound and contact:
            self.fields["recipient_name"].initial = contact.get_full_name()
            self.fields["recipient_email"].initial = contact.email


class ProjectClientFormDeliveryForm(forms.ModelForm):
    class Meta:
        model = ProjectClientForm
        fields = ("recipient_name", "recipient_email", "email_subject", "email_message")
        widgets = {"email_message": forms.Textarea(attrs={"rows": 4})}
        help_texts = {"email_subject": "Leave blank to use a branded default subject."}


class PublicProjectFormResponseForm(forms.Form):
    def __init__(self, *args, project_form, require_complete, **kwargs):
        self.project_form = project_form
        self.question_fields = []
        super().__init__(*args, **kwargs)
        for question in project_form.questions.all():
            name = f"question_{question.pk}"
            initial = ""
            try:
                initial = question.answer.value
            except ProjectFormAnswer.DoesNotExist:
                pass
            has_upload = False
            if question.field_type == ClientFormQuestion.FieldType.FILE:
                try:
                    question.upload
                except ProjectFormUpload.DoesNotExist:
                    pass
                else:
                    has_upload = True
            common = {
                "label": question.label,
                "help_text": question.help_text,
                "required": bool(require_complete and question.required and not has_upload),
                "initial": initial,
            }
            field_type = question.field_type
            if field_type == ClientFormQuestion.FieldType.LONG_TEXT:
                field = forms.CharField(max_length=10000, widget=forms.Textarea(attrs={"rows": 5}), **common)
            elif field_type == ClientFormQuestion.FieldType.EMAIL:
                field = forms.EmailField(max_length=320, **common)
            elif field_type == ClientFormQuestion.FieldType.NUMBER:
                field = forms.DecimalField(**common)
            elif field_type == ClientFormQuestion.FieldType.DATE:
                field = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), **common)
            elif field_type == ClientFormQuestion.FieldType.SELECT:
                field = forms.ChoiceField(
                    choices=[("", "Select one")] + [(item, item) for item in question.options],
                    **common,
                )
            elif field_type == ClientFormQuestion.FieldType.MULTI_SELECT:
                field = forms.MultipleChoiceField(
                    choices=[(item, item) for item in question.options],
                    widget=forms.CheckboxSelectMultiple,
                    **common,
                )
            elif field_type == ClientFormQuestion.FieldType.YES_NO:
                field = forms.ChoiceField(
                    choices=(("", "Select one"), ("yes", "Yes"), ("no", "No")),
                    **common,
                )
            elif field_type == ClientFormQuestion.FieldType.FILE:
                common.pop("initial", None)
                field = forms.FileField(
                    validators=[validate_client_form_upload],
                    widget=forms.ClearableFileInput(
                        attrs={
                            "accept": ".pdf,.doc,.docx,.jpg,.jpeg,.png,.webp,.heic,.heif"
                        }
                    ),
                    **common,
                )
                if has_upload:
                    field.help_text = "A file is already saved. Choose another file to replace it."
            else:
                input_type = "tel" if field_type == ClientFormQuestion.FieldType.PHONE else "text"
                field = forms.CharField(max_length=500, widget=forms.TextInput(attrs={"type": input_type}), **common)
            self.fields[name] = field
            self.question_fields.append((question, self[name]))

    @property
    def sections(self):
        grouped = []
        for question, bound_field in self.question_fields:
            section = question.section or "Project information"
            if not grouped or grouped[-1][0] != section:
                grouped.append((section, []))
            grouped[-1][1].append(bound_field)
        return grouped
