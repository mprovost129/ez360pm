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
