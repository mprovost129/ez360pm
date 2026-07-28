from django import forms
from django.db import transaction

from clients.models import Client
from core.forms import CompanyScopedModelForm

from .models import Project
from .services import create_project, update_project_details


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
        self.fields["fixed_fee"].label = "Fixed fee amount"
        self.fields["hourly_rate"].help_text = (
            "Entering a fixed fee amount clears this rate automatically."
        )
        self.fields["fixed_fee"].help_text = (
            "Entering an amount switches billing to Fixed fee."
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
                self.add_error("fixed_fee", "Fixed-fee projects require a fee.")
        return cleaned

    @transaction.atomic
    def save(self, commit=True):
        if not commit:
            raise ValueError("ProjectForm must be saved with commit=True.")
        client = self.cleaned_data["client"]
        data = {
            field: self.cleaned_data[field]
            for field in self.Meta.fields
            if field != "client"
        }
        if self.instance.pk:
            self.instance = update_project_details(
                project=self.instance,
                client=client,
                project_data=data,
            )
            return self.instance

        self.instance = create_project(
            company=self.company,
            client=client,
            project_data=data,
        )
        return self.instance


class ProjectStatusForm(forms.Form):
    status = forms.ChoiceField(
        choices=Project.Status.choices,
        label="Project status",
        help_text=(
            "Changing status does not alter proposals, invoices, payments, or time records."
        ),
        widget=forms.Select(attrs={"aria-label": "Project status"}),
    )

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        if project is not None:
            self.fields["status"].initial = project.status
