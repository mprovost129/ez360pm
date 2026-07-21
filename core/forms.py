from django import forms
from django.core.exceptions import ImproperlyConfigured


class CompanyScopedModelForm(forms.ModelForm):
    """Base form that requires company context for ownership and FK scoping."""

    def __init__(self, *args, company=None, **kwargs):
        if company is None:
            raise ImproperlyConfigured(
                f"{self.__class__.__name__} requires a company argument."
            )
        self.company = company
        super().__init__(*args, **kwargs)
        if hasattr(self.instance, "company_id"):
            self.instance.company = company

    def scope_field(self, field_name, *, company_lookup="company"):
        """Limit a ModelChoice field to records owned by this form's company."""

        field = self.fields[field_name]
        queryset = field.queryset
        if company_lookup == "company" and hasattr(queryset, "for_company"):
            field.queryset = queryset.for_company(self.company)
        else:
            field.queryset = queryset.filter(**{company_lookup: self.company})

    def save(self, commit=True):
        if hasattr(self.instance, "company_id"):
            self.instance.company = self.company
        return super().save(commit=commit)
