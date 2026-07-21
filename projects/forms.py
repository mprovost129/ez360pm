from django import forms

from clients.models import Client
from core.forms import CompanyScopedModelForm

from .models import Project
from .services import create_project


class ProjectForm(CompanyScopedModelForm):
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
        if not self.instance.pk and self.company.default_hourly_rate:
            self.fields["hourly_rate"].initial = self.company.default_hourly_rate

    def clean(self):
        cleaned = super().clean()
        billing_type = cleaned.get("billing_type")
        if billing_type == Project.BillingType.HOURLY:
            if cleaned.get("hourly_rate") is None:
                self.add_error("hourly_rate", "Hourly projects require a rate.")
            if cleaned.get("fixed_fee") is not None:
                self.add_error("fixed_fee", "Clear the fixed fee for hourly billing.")
        elif billing_type == Project.BillingType.FLAT_FEE:
            if cleaned.get("fixed_fee") is None:
                self.add_error("fixed_fee", "Flat-fee projects require a fee.")
            if cleaned.get("hourly_rate") is not None:
                self.add_error("hourly_rate", "Clear the hourly rate for flat-fee billing.")
        return cleaned

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

