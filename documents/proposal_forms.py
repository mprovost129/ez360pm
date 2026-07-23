from datetime import timedelta
from decimal import Decimal

from django import forms
from django.utils import timezone

from core.forms import CompanyScopedModelForm
from projects.models import Project

from .models import Document
from .proposal_services import (
    apply_retainer_credit,
    available_retainer_credit,
    create_proposal,
    create_retainer_invoice,
    sanitize_rich_text,
)


class ProposalCreateForm(CompanyScopedModelForm):
    number = forms.CharField(max_length=30, required=False)

    field_groups = (
        ("Estimate / proposal", ("project", "number", "issue_date")),
        ("Customer settings", ("terms",)),
        ("Internal", ("notes",)),
    )

    class Meta:
        model = Document
        fields = ("project", "number", "issue_date", "terms", "notes")
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "terms": forms.Textarea(attrs={"rows": 4}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "terms": "Customer terms",
            "notes": "Internal notes",
        }
        help_texts = {
            "number": "Leave blank to generate the next proposal number.",
            "notes": "Only you can see these notes.",
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, company=company, **kwargs)
        self.instance.doc_type = Document.Type.PROPOSAL
        self.instance.invoice_kind = ""
        self.instance.due_date = None
        self.fields["project"].queryset = Project.objects.for_company(company)
        project_id = self.initial.get("project")
        if project_id:
            locked_project = self.fields["project"].queryset.filter(pk=project_id).first()
            if locked_project:
                self.fields["project"].initial = locked_project
                self.fields["project"].disabled = True
                self.fields["project"].help_text = "Selected from the project page."

    def save(self, commit=True):
        if not commit:
            raise ValueError("ProposalCreateForm must be saved with commit=True.")
        project = self.cleaned_data["project"]
        data = {
            field: self.cleaned_data[field]
            for field in self.Meta.fields
            if field != "project"
        }
        self.instance = create_proposal(
            company=self.company,
            project=project,
            proposal_data=data,
        )
        return self.instance


class ProposalEditForm(CompanyScopedModelForm):
    field_groups = (
        ("Estimate / proposal", ("number", "issue_date")),
        ("Customer settings", ("terms",)),
        ("Internal", ("notes",)),
    )

    class Meta:
        model = Document
        fields = ("number", "issue_date", "terms", "notes")
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "terms": forms.Textarea(attrs={"rows": 4}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "terms": "Customer terms",
            "notes": "Internal notes",
        }
        help_texts = {"notes": "Only you can see these notes."}

    def clean_terms(self):
        return sanitize_rich_text(self.cleaned_data["terms"])

    def clean_notes(self):
        return sanitize_rich_text(self.cleaned_data["notes"])


class ProposalSectionForm(forms.Form):
    heading = forms.CharField(max_length=255)
    body = forms.CharField(widget=forms.Textarea(attrs={"rows": 6}))


class AcceptanceForm(forms.Form):
    signer_name = forms.CharField(max_length=255, label="Your name")
    signer_email = forms.EmailField(label="Your email")


class RetainerInvoiceForm(forms.Form):
    mode = forms.ChoiceField(
        choices=(("percentage", "Percentage of accepted proposal"), ("amount", "Fixed amount"))
    )
    value = forms.DecimalField(min_value=Decimal("0.01"), max_digits=12, decimal_places=2)
    number = forms.CharField(max_length=30, required=False)
    issue_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    due_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    terms = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    accept_payments = forms.BooleanField(required=False)

    def __init__(self, *args, proposal, **kwargs):
        self.proposal = proposal
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["mode"].label = "Retainer calculation"
        self.fields["value"].label = "Percentage or amount"
        self.fields["value"].help_text = (
            "Enter a percentage when Percentage is selected, otherwise enter a dollar amount."
        )
        self.fields["value"].widget.attrs["data-proposal-total"] = str(
            proposal.accepted_total or proposal.total
        )
        self.fields["number"].help_text = "Leave blank to generate the next invoice number."
        self.fields["terms"].label = "Customer terms"
        self.fields["notes"].label = "Internal notes"
        self.fields["notes"].help_text = "Only you can see these notes."
        self.fields["accept_payments"].label = "Allow online payment with Stripe"
        self.fields["issue_date"].initial = today
        self.fields["due_date"].initial = today + timedelta(days=30)
        self.fields["accept_payments"].initial = proposal.company.accept_payments_default

    def save(self):
        data = {
            field: self.cleaned_data[field]
            for field in ("number", "issue_date", "due_date", "terms", "notes", "accept_payments")
        }
        return create_retainer_invoice(
            proposal=self.proposal,
            mode=self.cleaned_data["mode"],
            value=self.cleaned_data["value"],
            invoice_data=data,
        )


class RetainerChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, invoice):
        available = available_retainer_credit(invoice)
        return f"{invoice.number} · ${available:.2f} available"


class InvoiceCreditForm(forms.Form):
    source_invoice = RetainerChoiceField(
        queryset=Document.objects.none(),
        label="Paid retainer",
    )
    amount = forms.DecimalField(min_value=Decimal("0.01"), max_digits=12, decimal_places=2)

    def __init__(self, *args, destination_invoice, **kwargs):
        self.destination_invoice = destination_invoice
        super().__init__(*args, **kwargs)
        paid_retainers = Document.objects.filter(
            company=destination_invoice.company,
            project=destination_invoice.project,
            doc_type=Document.Type.INVOICE,
            invoice_kind=Document.InvoiceKind.RETAINER,
            status=Document.Status.PAID,
        )
        self.fields["source_invoice"].queryset = paid_retainers
        self.fields["amount"].label = "Credit to apply"
        self.fields["amount"].help_text = (
            "The credit cannot exceed the retainer available or the remaining invoice charges."
        )
        if not self.is_bound and paid_retainers.count() == 1:
            available = available_retainer_credit(paid_retainers.first())
            remaining = max(
                destination_invoice.subtotal
                + destination_invoice.tax_total
                - destination_invoice.credit_total,
                Decimal("0.00"),
            )
            self.fields["amount"].initial = min(available, remaining)

    def clean(self):
        cleaned = super().clean()
        source = cleaned.get("source_invoice")
        if source and available_retainer_credit(source) <= 0:
            self.add_error("source_invoice", "This retainer has no available credit.")
        return cleaned

    def save(self):
        return apply_retainer_credit(
            source_invoice=self.cleaned_data["source_invoice"],
            destination_invoice=self.destination_invoice,
            amount=self.cleaned_data["amount"],
        )
