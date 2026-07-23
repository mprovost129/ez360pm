from datetime import timedelta
from decimal import Decimal

from django import forms
from django.utils import timezone

from clients.models import Client
from core.forms import CompanyScopedModelForm
from projects.models import Project, TimeEntry

from .models import Document, LineItem, Payment
from .services import create_invoice, record_payment, save_line_item, update_payment


class InvoiceCreateForm(CompanyScopedModelForm):
    number = forms.CharField(
        max_length=30,
        required=False,
        help_text="Leave blank to generate the next invoice number.",
    )

    field_groups = (
        ("Invoice", ("project", "invoice_kind", "number", "issue_date", "due_date")),
        ("Customer settings", ("terms", "accept_payments")),
        ("Internal", ("notes",)),
    )

    class Meta:
        model = Document
        fields = (
            "project",
            "invoice_kind",
            "number",
            "issue_date",
            "due_date",
            "terms",
            "notes",
            "accept_payments",
        )
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "terms": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "invoice_kind": "Invoice type",
            "terms": "Customer terms",
            "notes": "Internal notes",
            "accept_payments": "Allow online payment with Stripe",
        }
        help_texts = {
            "notes": "Only you can see these notes.",
            "accept_payments": "Shows a Pay button on the customer invoice when Stripe is configured.",
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, company=company, **kwargs)
        self.instance.doc_type = Document.Type.INVOICE
        self.fields["project"].queryset = Project.objects.for_company(company)
        self.fields["accept_payments"].initial = company.accept_payments_default
        self.fields["invoice_kind"].initial = Document.InvoiceKind.FINAL
        if not self.is_bound:
            self.fields["due_date"].initial = timezone.localdate() + timedelta(
                days=company.default_invoice_due_days
            )
            self.fields["terms"].initial = company.default_invoice_terms
        project_id = self.initial.get("project")
        if project_id:
            locked_project = self.fields["project"].queryset.filter(pk=project_id).first()
            if locked_project:
                self.fields["project"].initial = locked_project
                self.fields["project"].disabled = True
                self.fields["project"].help_text = "Selected from the project page."

    def save(self, commit=True):
        if not commit:
            raise ValueError("InvoiceCreateForm must be saved with commit=True.")
        project = self.cleaned_data["project"]
        data = {
            field: self.cleaned_data[field]
            for field in self.Meta.fields
            if field != "project"
        }
        self.instance = create_invoice(
            company=self.company,
            project=project,
            invoice_data=data,
        )
        return self.instance


class InvoiceEditForm(CompanyScopedModelForm):
    field_groups = (
        ("Invoice", ("number", "issue_date", "due_date")),
        ("Customer settings", ("terms", "accept_payments")),
        ("Internal", ("notes",)),
    )

    class Meta:
        model = Document
        fields = ("number", "issue_date", "due_date", "terms", "notes", "accept_payments")
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "terms": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "terms": "Customer terms",
            "notes": "Internal notes",
            "accept_payments": "Allow online payment with Stripe",
        }
        help_texts = {
            "notes": "Only you can see these notes.",
            "accept_payments": "Shows a Pay button on the customer invoice when Stripe is configured.",
        }


class LineItemForm(forms.ModelForm):
    class Meta:
        model = LineItem
        fields = ("description", "rate", "quantity", "tax_rate")
        labels = {
            "rate": "Unit price",
            "quantity": "Quantity / hours",
            "tax_rate": "Tax %",
        }
        widgets = {
            "rate": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "quantity": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "tax_rate": forms.NumberInput(attrs={"step": "0.001", "min": "0"}),
        }

    def __init__(self, *args, document, **kwargs):
        self.document = document
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.instance.pk:
            self.fields["quantity"].initial = Decimal("1.00")
            self.fields["tax_rate"].initial = document.company.default_tax_rate

    def save(self, commit=True):
        if not commit:
            raise ValueError("LineItemForm must be saved with commit=True.")
        data = {field: self.cleaned_data[field] for field in self.Meta.fields}
        self.instance = save_line_item(
            document=self.document,
            line=self.instance if self.instance.pk else None,
            line_data=data,
        )
        return self.instance


class TimeEntryCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(name, value, label, selected, index, **kwargs)
        entry = getattr(value, "instance", None)
        if entry is not None:
            rate = entry.project.hourly_rate or Decimal("0.00")
            option["attrs"].update(
                {
                    "data-description": entry.description.strip()
                    or "Professional services",
                    "data-hours": str(entry.duration_hours),
                    "data-amount": str(rate * entry.duration_hours),
                }
            )
        return option


class TimeEntryChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, entry):
        rate = entry.project.hourly_rate or Decimal("0.00")
        amount = rate * entry.duration_hours
        description = entry.description.strip() or "Professional services"
        local_start = timezone.localtime(entry.start_time)
        date_label = local_start.strftime("%b %d, %Y").replace(" 0", " ")
        return (
            f"{date_label} · {description} · "
            f"{entry.duration_hours}h · ${rate:.2f}/hr · ${amount:.2f}"
        )


class TimeAttachmentForm(forms.Form):
    entries = TimeEntryChoiceField(
        queryset=TimeEntry.objects.none(),
        widget=TimeEntryCheckboxSelectMultiple,
        label="Unbilled time",
    )
    grouping = forms.ChoiceField(
        choices=(
            ("individual", "One line per time entry"),
            ("description", "Group identical descriptions"),
            ("combined", "One combined line"),
        ),
        help_text="Choose how the selected entries should appear on the customer invoice.",
    )

    def __init__(self, *args, invoice, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["entries"].queryset = TimeEntry.objects.filter(
            company=invoice.company,
            project=invoice.project,
            end_time__isnull=False,
            billable=True,
            status=TimeEntry.Status.LOGGED,
            line_item__isnull=True,
        ).select_related("project")


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ("amount", "method", "received_at", "reference")
        widgets = {"received_at": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, invoice, **kwargs):
        self.invoice = invoice
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["amount"].initial = invoice.outstanding_balance

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        other_paid = self.invoice.amount_paid
        if self.instance.pk:
            other_paid -= self.instance.amount
        if other_paid + amount > self.invoice.total:
            raise forms.ValidationError("Payments cannot exceed the invoice total.")
        return amount

    def save(self, commit=True):
        if not commit:
            raise ValueError("PaymentForm must be saved with commit=True.")
        data = {field: self.cleaned_data[field] for field in self.Meta.fields}
        if self.instance.pk:
            self.instance = update_payment(payment=self.instance, payment_data=data)
        else:
            self.instance = record_payment(invoice=self.invoice, payment_data=data)
        return self.instance


class VoidInvoiceForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)


class InvoiceFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        label="Search",
        widget=forms.TextInput(attrs={"placeholder": "Invoice, project, or customer"}),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[("", "All statuses")] + Document.Status.choices,
    )
    invoice_kind = forms.ChoiceField(
        required=False,
        choices=[("", "All kinds")] + Document.InvoiceKind.choices,
    )
    client = forms.ModelChoiceField(queryset=Client.objects.none(), required=False)
    project = forms.ModelChoiceField(queryset=Project.objects.none(), required=False)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.for_company(company).ordered_for_list()
        self.fields["project"].queryset = Project.objects.for_company(company)
