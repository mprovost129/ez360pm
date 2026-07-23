from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Project


@transaction.atomic
def change_project_status(*, project, status):
    project = Project.objects.select_for_update().get(pk=project.pk)
    if status not in Project.Status.values:
        raise ValidationError("Choose a valid project status.")
    if project.status == status:
        return project
    if status in {
        Project.Status.ON_HOLD,
        Project.Status.COMPLETED,
        Project.Status.CANCELED,
    } and project.time_entries.filter(end_time__isnull=True).exists():
        raise ValidationError(
            "Stop the running timer before placing this project on hold or closing it."
        )
    project.status = status
    project.save(update_fields=["status", "updated_at"])
    return project


@transaction.atomic
def approve_project(*, project):
    project = Project.objects.select_for_update().get(pk=project.pk)
    if project.status == Project.Status.APPROVED:
        return project
    if project.status != Project.Status.LEAD:
        raise ValidationError("Only lead projects can be approved.")
    project.status = Project.Status.APPROVED
    project.save(update_fields=["status", "updated_at"])
    return project


@transaction.atomic
def activate_project_if_funded(*, invoice):
    from documents.models import Document

    invoice = Document.objects.select_for_update().select_related("project").get(pk=invoice.pk)
    project = Project.objects.select_for_update().get(pk=invoice.project_id)
    if (
        invoice.doc_type == Document.Type.INVOICE
        and invoice.invoice_kind == Document.InvoiceKind.RETAINER
        and invoice.status == Document.Status.PAID
        and project.status == Project.Status.APPROVED
    ):
        project.status = Project.Status.ACTIVE
        project.save(update_fields=["status", "updated_at"])
    return project


@transaction.atomic
def start_without_retainer(*, project):
    from documents.models import Document

    project = Project.objects.select_for_update().get(pk=project.pk)
    if project.status != Project.Status.APPROVED:
        raise ValidationError("Only approved projects can be started.")
    has_retainer = Document.objects.filter(
        project=project,
        doc_type=Document.Type.INVOICE,
        invoice_kind=Document.InvoiceKind.RETAINER,
    ).exclude(status=Document.Status.VOID).exists()
    if has_retainer:
        raise ValidationError("This project has a retainer invoice that must be resolved.")
    project.status = Project.Status.ACTIVE
    project.save(update_fields=["status", "updated_at"])
    return project


@transaction.atomic
def complete_paid_project(*, project):
    from documents.models import Document

    project = Project.objects.select_for_update().get(pk=project.pk)
    if project.status not in {Project.Status.ACTIVE, Project.Status.ON_HOLD}:
        raise ValidationError("Only active or on-hold projects can be completed.")
    has_paid_final = Document.objects.filter(
        project=project,
        doc_type=Document.Type.INVOICE,
        invoice_kind=Document.InvoiceKind.FINAL,
        status=Document.Status.PAID,
    ).exists()
    if not has_paid_final:
        raise ValidationError("A paid final invoice is required before completion.")
    project.status = Project.Status.COMPLETED
    project.save(update_fields=["status", "updated_at"])
    return project
