from django.core.exceptions import ImproperlyConfigured


class CompanyScopedQuerysetMixin:
    """Scope a class-based view queryset to the authenticated user's company."""

    company_lookup = "company"

    def get_company(self):
        user = getattr(self.request, "user", None)
        company = getattr(user, "company", None)
        if company is None:
            raise ImproperlyConfigured(
                "CompanyScopedQuerysetMixin requires a user with a company."
            )
        return company

    def get_queryset(self):
        queryset = super().get_queryset()
        company = self.get_company()
        if self.company_lookup == "company" and hasattr(queryset, "for_company"):
            return queryset.for_company(company)
        return queryset.filter(**{self.company_lookup: company})

