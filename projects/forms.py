from django import forms
from django.db import transaction

from clients.models import Client
from core.forms import CompanyScopedModelForm

from .models import Project
from .services import create_project
from .workflow import change_project_status


class ProjectForm(CompanyScopedModelForm):
    field_groups = (
        ("Project", ("client", "number", "name", "description")),
        (
            "Site",
            (
                "address_1",
                "address_2",
                "city",
                "state",
                "postal_code",
                "municipality",
                "parcel_id",
            ),
        ),
        (
            "Billing",
            ("billing_type", "hourly_rate", "fixed_fee", "estimated_hours"),
        ),
    )

    number = forms.CharField(
        max_length=30,
        required=False,
        help_text="Leave blank to generate the next YYMM### number.",
    )

    class Meta:
        model = Project
        fields = (
            "client",
            "number",
            "name",
            "description",
            "address_1",
            "address_2",
            "city",
            "state",
            "postal_code",
            "municipality",
            "parcel_id",
            "billing_type",
            "hourly_rate",
            "fixed_fee",
            "estimated_hours",
        )
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, company=company, **kwargs)
        self.fields["client"].queryset = Client.objects.for_company(
            self.company
        ).ordered_for_list()
        client_id = getattr(self.initial.get("client"), "pk", self.initial.get("client"))
        if not self.instance.pk and client_id:
            locked_client = self.fields["client"].queryset.filter(pk=client_id).first()
            if locked_client:
                self.fields["client"].initial = locked_client
                self.fields["client"].disabled = True
                self.fields["client"].help_text = "Selected from the client page."
        if not self.instance.pk and self.company.default_hourly_rate:
            self.fields["hourly_rate"].initial = self.company.default_hourly_rate
        self.fields["hourly_rate"].help_text = (
            "Entering a fixed fee clears this rate automatically."
        )
        self.fields["fixed_fee"].help_text = (
            "Entering a fixed fee switches billing to Flat fee."
        )

    def clean(self):
        cleaned = super().clean()
        billing_type = cleaned.get("billing_type")
        fixed_fee = cleaned.get("fixed_fee")

        # A fixed fee is an explicit billing choice. It wins over the hourly
        # default populated from Company settings, including without JavaScript.
        if fixed_fee is not None:
            billing_type = Project.BillingType.FLAT_FEE
            cleaned["billing_type"] = billing_type
            cleaned["hourly_rate"] = None

        if billing_type == Project.BillingType.HOURLY:
            if cleaned.get("hourly_rate") is None:
                self.add_error("hourly_rate", "Hourly projects require a rate.")
        elif billing_type == Project.BillingType.FLAT_FEE:
            cleaned["hourly_rate"] = None
            if fixed_fee is None:
                self.add_error("fixed_fee", "Flat-fee projects require a fee.")
        return cleaned

    @transaction.atomic
    def save(self, commit=True):
        if not commit:
            raise ValueError("ProjectForm must be saved with commit=True.")
        if self.instance.pk:
            return super().save(commit=True)

        client = self.cleaned_data["client"]
        data = {
            field: self.cleaned_data[field]
            for field in self.Meta.fields
            if field != "client"
        }
        self.instance = create_project(
            company=self.company,
            client=client,
            project_data=data,
        )
        return self.instance


class ProjectEditForm(ProjectForm):
    status = forms.ChoiceField(
        choices=Project.Status.choices,
        label="Project status",
        help_text=(
            "Status normally advances through proposals and payments. A manual change "
            "does not alter invoices, proposals, payments, or recorded time."
        ),
    )
    confirm_status_change = forms.BooleanField(
        required=False,
        label="Confirm this manual status change",
        help_text="Required only when selecting a different status.",
    )
    field_groups = (
        ProjectForm.field_groups[0],
        ("Workflow", ("status", "confirm_status_change")),
        *ProjectForm.field_groups[1:],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_status = self.instance.status
        self.fields["status"].initial = self.original_status

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get("status")
        if status and status != self.original_status:
            if not cleaned.get("confirm_status_change"):
                self.add_error(
                    "confirm_status_change",
                    "Confirm the manual status change before saving.",
                )
            if status in {
                Project.Status.ON_HOLD,
                Project.Status.COMPLETED,
                Project.Status.CANCELED,
            } and self.instance.time_entries.filter(end_time__isnull=True).exists():
                self.add_error(
                    "status",
                    "Stop the running timer before placing this project on hold or closing it.",
                )
        return cleaned

    @transaction.atomic
    def save(self, commit=True):
        if not commit:
            raise ValueError("ProjectEditForm must be saved with commit=True.")
        requested_status = self.cleaned_data["status"]
        project = super().save(commit=True)
        self.instance = change_project_status(
            project=project,
            status=requested_status,
        )
        return self.instance
