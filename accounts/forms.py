from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils import timezone

from .models import Company


class EmailAuthenticationForm(AuthenticationForm):
    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class CompanySettingsForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = (
            "name",
            "address_1",
            "address_2",
            "city",
            "state",
            "postal_code",
            "country",
            "phone",
            "email",
            "logo",
            "default_hourly_rate",
            "accept_payments_default",
            "default_proposal_terms",
            "default_invoice_terms",
            "default_invoice_due_days",
            "default_tax_rate",
            "books_closed_through",
        )
        labels = {
            "accept_payments_default": "Allow Stripe payments by default",
            "default_proposal_terms": "Default proposal terms",
            "default_invoice_terms": "Default invoice terms",
            "default_invoice_due_days": "Default invoice payment period (days)",
            "default_tax_rate": "Default tax rate (%)",
            "books_closed_through": "Financial records locked through",
        }
        widgets = {
            "default_proposal_terms": forms.Textarea(attrs={"rows": 4}),
            "default_invoice_terms": forms.Textarea(attrs={"rows": 4}),
            "default_tax_rate": forms.NumberInput(attrs={"step": "0.001", "min": "0"}),
            "books_closed_through": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_books_closed_through(self):
        close_date = self.cleaned_data.get("books_closed_through")
        if close_date is None:
            return close_date
        if close_date > timezone.localdate():
            raise forms.ValidationError("The financial lock date cannot be in the future.")
        if self.instance.pk:
            # Import here to avoid coupling the accounts model module to billing.
            from documents.models import Payment

            pending_fees = Payment.objects.filter(
                document__company=self.instance,
                method=Payment.Method.STRIPE,
                fee_pending=True,
                received_at__lte=close_date,
            ).exists()
            if pending_fees:
                raise forms.ValidationError(
                    "Resolve all pending Stripe fees through this date before "
                    "locking the financial period."
                )
        return close_date

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo and hasattr(logo, "content_type"):
            if logo.size > 2 * 1024 * 1024:
                raise forms.ValidationError("Logo must be 2 MB or smaller.")
            if logo.content_type not in {"image/jpeg", "image/png", "image/webp"}:
                raise forms.ValidationError("Use a JPEG, PNG, or WebP logo.")
        return logo
