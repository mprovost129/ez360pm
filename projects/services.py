from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import Company
from core.validation import validate_same_company

from .models import Project, ProjectNumberSequence


def allocate_project_number(*, company, on_date=None):
    local_date = on_date or timezone.localdate()
    period = local_date.strftime("%y%m")
    with transaction.atomic():
        locked_company = Company.objects.select_for_update().get(pk=company.pk)
        sequence, _created = ProjectNumberSequence.objects.get_or_create(
            company=locked_company,
            period=period,
        )
        if sequence.last_value >= 999:
            raise ValidationError(f"Project number sequence {period} is exhausted.")
        sequence.last_value += 1
        sequence.save(update_fields=["last_value"])
        return f"{period}{sequence.last_value:03d}"


@transaction.atomic
def create_project(*, company, client, project_data):
    validate_same_company(company, client)
    data = dict(project_data)
    number = data.pop("number", "").strip()
    if not number:
        number = allocate_project_number(company=company)
    project = Project(company=company, client=client, number=number, **data)
    project.full_clean()
    project.save()
    return project

