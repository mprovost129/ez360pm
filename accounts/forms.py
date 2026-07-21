from django import forms

from .models import Company


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
        )

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo and hasattr(logo, "content_type"):
            if logo.size > 2 * 1024 * 1024:
                raise forms.ValidationError("Logo must be 2 MB or smaller.")
            if logo.content_type not in {"image/jpeg", "image/png", "image/webp"}:
                raise forms.ValidationError("Use a JPEG, PNG, or WebP logo.")
        return logo
