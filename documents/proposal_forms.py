from decimal import Decimal

from django import forms

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

    class Meta:
        model = Document
        fields = ("project", "number", "issue_date", "terms", "notes")
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "terms": forms.Textarea(attrs={"rows": 4}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, company=company, **kwargs)
        self.instance.doc_type = Document.Type.PROPOSAL
        self.instance.invoice_kind = ""
        self.instance.due_date = None
        self.fields["project"].queryset = Project.objects.for_company(company)

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
    class Meta:
        model = Document
        fields = ("number", "issue_date", "terms", "notes")
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "terms": forms.Textarea(attrs={"rows": 4}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

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
        self.fields["issue_date"].initial = proposal.issue_date
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


class InvoiceCreditForm(forms.Form):
    source_invoice = forms.ModelChoiceField(queryset=Document.objects.none())
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
