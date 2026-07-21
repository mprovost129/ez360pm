from django.core.exceptions import ValidationError


def validate_same_company(company, *related_objects):
    """Reject direct company-owned objects from a different company."""

    expected_id = getattr(company, "pk", company)
    for related in related_objects:
        if related is None:
            continue
        actual_id = getattr(related, "company_id", None)
        if actual_id is None:
            raise TypeError(
                f"{related.__class__.__name__} does not expose a direct company_id."
            )
        if actual_id != expected_id:
            raise ValidationError("Related records must belong to the same company.")

