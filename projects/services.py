from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import Company
from core.validation import validate_same_company

from .models import Project, ProjectNumberSequence

PROJECT_EDITABLE_FIELDS = {
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
}


def _validated_project_data(data):
    unknown = set(data) - PROJECT_EDITABLE_FIELDS
    if unknown:
        raise ValidationError(
            f"Unsupported project fields: {', '.join(sorted(unknown))}."
        )
    return dict(data)


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
    data = _validated_project_data(project_data)
    number = data.pop("number", "").strip()
    if not number:
        number = allocate_project_number(company=company)
    project = Project(company=company, client=client, number=number, **data)
    project.full_clean()
    project.save()
    return project


@transaction.atomic
def update_project_details(*, project, client, project_data):
    validate_same_company(project.company, client)
    data = _validated_project_data(project_data)
    locked = Project.objects.select_for_update().get(pk=project.pk)

    if client.pk != locked.client_id:
        has_history = (
            locked.documents.exists()
            or locked.time_entries.exists()
            or locked.notes.exists()
        )
        if locked.status != Project.Status.LEAD or has_history:
            raise ValidationError(
                "A project with workflow history cannot be moved to another client."
            )
        locked.client = client

    for field, value in data.items():
        setattr(locked, field, value)
    locked.full_clean()
    update_fields = [*data.keys(), "client", "updated_at"]
    locked.save(update_fields=list(dict.fromkeys(update_fields)))
    return locked
