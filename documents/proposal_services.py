from datetime import timedelta
from decimal import Decimal

import bleach
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from projects.models import Project
from projects.workflow import approve_project

from .models import Document, InvoiceCredit, LineItem
from .services import (
    allocate_document_number,
    create_invoice,
    money,
    recalculate_document_totals,
)

ALLOWED_TAGS = ("p", "br", "strong", "em", "ul", "ol", "li", "a")
ALLOWED_ATTRIBUTES = {"a": ("href", "title")}
ALLOWED_PROTOCOLS = ("http", "https", "mailto")


def sanitize_rich_text(value):
    return bleach.clean(
        value or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )


def sanitize_plain_text(value):
    return bleach.clean(value or "", tags=(), strip=True).strip()


@transaction.atomic
def create_proposal(*, company, project, proposal_data):
    try:
        project = Project.objects.for_company(company).get(pk=project.pk)
    except Project.DoesNotExist:
        raise ValidationError("Project must belong to the company.") from None
    data = dict(proposal_data)
    number = data.pop("number", "").strip() or allocate_document_number(
        company=company,
        doc_type=Document.Type.PROPOSAL,
        on_date=data.get("issue_date"),
    )
    data["terms"] = sanitize_rich_text(data.get("terms"))
    data["notes"] = sanitize_rich_text(data.get("notes"))
    proposal = Document(
        company=company,
        project=project,
        doc_type=Document.Type.PROPOSAL,
        invoice_kind="",
        number=number,
        due_date=None,
        accept_payments=False,
        **data,
    )
    proposal.full_clean()
    proposal.save()
    return proposal


@transaction.atomic
def save_proposal_section(*, proposal, heading, body, index=None):
    proposal = Document.objects.select_for_update().get(pk=proposal.pk)
    if proposal.doc_type != Document.Type.PROPOSAL or not proposal.is_editable:
        raise ValidationError("Only draft proposals can be edited.")
    section = {
        "heading": sanitize_plain_text(heading),
        "body": sanitize_rich_text(body),
    }
    sections = list(proposal.body_sections)
    if index is None:
        sections.append(section)
    elif index < 0 or index >= len(sections):
        raise ValidationError("Proposal section no longer exists.")
    else:
        sections[index] = section
    proposal.body_sections = sections
    proposal.save(update_fields=["body_sections", "updated_at"])
    return proposal


@transaction.atomic
def delete_proposal_section(*, proposal, index):
    proposal = Document.objects.select_for_update().get(pk=proposal.pk)
    if proposal.doc_type != Document.Type.PROPOSAL or not proposal.is_editable:
        raise ValidationError("Only draft proposals can be edited.")
    sections = list(proposal.body_sections)
    if index < 0 or index >= len(sections):
        raise ValidationError("Proposal section no longer exists.")
    sections.pop(index)
    proposal.body_sections = sections
    proposal.save(update_fields=["body_sections", "updated_at"])


@transaction.atomic
def move_proposal_section(*, proposal, index, direction):
    proposal = Document.objects.select_for_update().get(pk=proposal.pk)
    if proposal.doc_type != Document.Type.PROPOSAL or not proposal.is_editable:
        raise ValidationError("Only draft proposals can be edited.")
    sections = list(proposal.body_sections)
    if index < 0 or index >= len(sections):
        raise ValidationError("Proposal section no longer exists.")
    offset = {"up": -1, "down": 1}.get(direction)
    if offset is None:
        raise ValidationError("Unknown section movement direction.")
    target = index + offset
    if target < 0 or target >= len(sections):
        return proposal
    sections[index], sections[target] = sections[target], sections[index]
    proposal.body_sections = sections
    proposal.save(update_fields=["body_sections", "updated_at"])
    return proposal


@transaction.atomic
def accept_proposal(*, proposal, signer_name, signer_email, ip_address, at=None):
    proposal = Document.objects.select_for_update().select_related("project").get(pk=proposal.pk)
    if proposal.doc_type != Document.Type.PROPOSAL:
        raise ValidationError("Only proposals can be accepted.")
    if proposal.status == Document.Status.ACCEPTED:
        return proposal
    if proposal.status not in {Document.Status.SENT, Document.Status.VIEWED}:
        raise ValidationError("This proposal is not open for acceptance.")
    proposal.status = Document.Status.ACCEPTED
    proposal.responded_at = at or timezone.now()
    proposal.accepted_by_name = sanitize_plain_text(signer_name)
    proposal.accepted_by_email = signer_email.strip().lower()
    proposal.accepted_total = proposal.total
    proposal.acceptance_ip = ip_address
    proposal.save(
        update_fields=[
            "status",
            "responded_at",
            "accepted_by_name",
            "accepted_by_email",
            "accepted_total",
            "acceptance_ip",
            "updated_at",
        ]
    )
    approve_project(project=proposal.project)
    return proposal


@transaction.atomic
def decline_proposal(*, proposal, at=None):
    proposal = Document.objects.select_for_update().get(pk=proposal.pk)
    if proposal.doc_type != Document.Type.PROPOSAL:
        raise ValidationError("Only proposals can be declined.")
    if proposal.status == Document.Status.DECLINED:
        return proposal
    if proposal.status not in {Document.Status.SENT, Document.Status.VIEWED}:
        raise ValidationError("This proposal is not open for response.")
    proposal.status = Document.Status.DECLINED
    proposal.responded_at = at or timezone.now()
    proposal.save(update_fields=["status", "responded_at", "updated_at"])
    return proposal


@transaction.atomic
def withdraw_proposal(*, proposal):
    proposal = Document.objects.select_for_update().get(pk=proposal.pk)
    if proposal.doc_type != Document.Type.PROPOSAL or proposal.status not in {
        Document.Status.SENT,
        Document.Status.VIEWED,
    }:
        raise ValidationError("Only an open proposal can be withdrawn.")
    proposal.status = Document.Status.WITHDRAWN
    proposal.save(update_fields=["status", "updated_at"])
    return proposal


@transaction.atomic
def create_retainer_invoice(*, proposal, mode, value, invoice_data):
    proposal = Document.objects.select_for_update().select_related("project", "company").get(
        pk=proposal.pk
    )
    if proposal.doc_type != Document.Type.PROPOSAL or proposal.status != Document.Status.ACCEPTED:
        raise ValidationError("Deposit invoices require an accepted proposal.")
    value = Decimal(value)
    if mode == "percentage":
        if value <= 0 or value > 100:
            raise ValidationError("Deposit percentage must be between 0 and 100.")
        amount = money(proposal.accepted_total * value / Decimal("100"))
    elif mode == "amount":
        amount = money(value)
    else:
        raise ValidationError("Unknown deposit calculation mode.")
    if amount <= 0 or amount > proposal.accepted_total:
        raise ValidationError("Deposit must be positive and no more than the accepted total.")
    existing_deposits = proposal.derived_invoices.filter(
        doc_type=Document.Type.INVOICE,
        invoice_kind=Document.InvoiceKind.RETAINER,
    ).exclude(status=Document.Status.VOID)
    existing_total = sum(
        (invoice.amount_due for invoice in existing_deposits),
        Decimal("0.00"),
    )
    if money(existing_total + amount) > proposal.accepted_total:
        raise ValidationError("Deposits cannot exceed the accepted proposal total.")

    data = dict(invoice_data)
    data.update(
        invoice_kind=Document.InvoiceKind.RETAINER,
        source_proposal=proposal,
        deposit_amount=amount,
    )
    invoice = create_invoice(
        company=proposal.company,
        project=proposal.project,
        invoice_data=data,
    )
    LineItem.objects.bulk_create(
        [
            LineItem(
                document=invoice,
                order=line.order,
                description=line.description,
                rate=line.rate,
                quantity=line.quantity,
                tax_rate=line.tax_rate,
                line_total=line.line_total,
            )
            for line in proposal.line_items.all()
        ]
    )
    invoice = recalculate_document_totals(document=invoice)
    if invoice.deposit_amount > invoice.total:
        raise ValidationError("Deposit cannot exceed the copied proposal total.")
    return invoice


def _next_staged_invoice_number(source):
    for sequence in range(2, 1000):
        number = f"{source.number}-{sequence}"
        if not Document.objects.filter(
            company=source.company,
            doc_type=Document.Type.INVOICE,
            number=number,
        ).exists():
            return number
    raise ValidationError("Unable to allocate the next invoice number in this billing series.")


@transaction.atomic
def create_final_invoice_from_deposit(*, source_invoice, at=None):
    source = (
        Document.objects.select_for_update()
        .select_related("company", "project")
        .prefetch_related("line_items")
        .get(pk=source_invoice.pk)
    )
    if source.doc_type != Document.Type.INVOICE or source.invoice_kind != Document.InvoiceKind.RETAINER:
        raise ValidationError("Final invoices must be created from a deposit / retainer invoice.")
    if source.status != Document.Status.PAID:
        raise ValidationError("Record the full deposit payment before creating the final invoice.")
    if source.follow_up_invoices.exclude(status=Document.Status.VOID).exists():
        raise ValidationError("This deposit invoice already has an active final invoice.")
    if (
        source.source_proposal_id
        and source.source_proposal.derived_invoices.filter(
            doc_type=Document.Type.INVOICE,
            invoice_kind=Document.InvoiceKind.FINAL,
        )
        .exclude(status=Document.Status.VOID)
        .exists()
    ):
        raise ValidationError("This proposal already has an active final invoice.")

    related_deposits = Document.objects.select_for_update().filter(
        company=source.company,
        project=source.project,
        doc_type=Document.Type.INVOICE,
        invoice_kind=Document.InvoiceKind.RETAINER,
    )
    if source.source_proposal_id:
        related_deposits = related_deposits.filter(
            source_proposal_id=source.source_proposal_id
        )
    else:
        related_deposits = related_deposits.filter(source_proposal__isnull=True)
    related_deposits = list(
        related_deposits.exclude(status=Document.Status.VOID).order_by("issue_date", "pk")
    )
    if any(deposit.status != Document.Status.PAID for deposit in related_deposits):
        raise ValidationError(
            "Pay or void every deposit invoice in this billing series before creating the final invoice."
        )

    issue_date = at or timezone.localdate()
    final = create_invoice(
        company=source.company,
        project=source.project,
        invoice_data={
            "invoice_kind": Document.InvoiceKind.FINAL,
            "source_proposal": source.source_proposal,
            "source_invoice": source,
            "number": _next_staged_invoice_number(source),
            "issue_date": issue_date,
            "due_date": issue_date
            + timedelta(days=source.company.default_invoice_due_days),
            "terms": source.terms,
            "notes": source.notes,
            "accept_payments": source.accept_payments,
        },
        populate_project_lines=False,
    )
    scope = source.source_proposal if source.source_proposal_id else source
    LineItem.objects.bulk_create(
        [
            LineItem(
                document=final,
                order=line.order,
                description=line.description,
                rate=line.rate,
                quantity=line.quantity,
                tax_rate=line.tax_rate,
                line_total=line.line_total,
            )
            for line in scope.line_items.all()
        ]
    )
    final = recalculate_document_totals(document=final)
    credit_plan = []
    for deposit in related_deposits:
        available = available_retainer_credit(deposit)
        if available > 0:
            credit_plan.append((deposit, available))
    if not credit_plan:
        raise ValidationError("The deposit invoice has no paid amount available to credit.")
    for deposit, credit_amount in credit_plan:
        if final.total <= 0:
            break
        apply_retainer_credit(
            source_invoice=deposit,
            destination_invoice=final,
            amount=min(credit_amount, final.total),
        )
        final.refresh_from_db()
    final.refresh_from_db()
    return final


def available_retainer_credit(retainer):
    applied = retainer.credits_given.aggregate(value=Sum("amount"))["value"] or Decimal("0")
    return max(retainer.amount_paid - applied, Decimal("0.00"))


@transaction.atomic
def apply_retainer_credit(*, source_invoice, destination_invoice, amount):
    source = Document.objects.select_for_update().get(pk=source_invoice.pk)
    destination = Document.objects.select_for_update().get(pk=destination_invoice.pk)
    if source.company_id != destination.company_id or source.project_id != destination.project_id:
        raise ValidationError("Retainer and final invoice must share a project and company.")
    if source.invoice_kind != Document.InvoiceKind.RETAINER or source.status != Document.Status.PAID:
        raise ValidationError("Credit source must be a paid retainer invoice.")
    if destination.invoice_kind != Document.InvoiceKind.FINAL or not destination.is_editable:
        raise ValidationError("Credits can only be added to a draft final invoice.")
    amount = money(amount)
    available = available_retainer_credit(source)
    remaining_charges = money(destination.subtotal + destination.tax_total - destination.credit_total)
    if amount <= 0 or amount > available or amount > remaining_charges:
        raise ValidationError("Credit exceeds the available retainer or invoice charges.")
    credit = InvoiceCredit(
        source_invoice=source,
        destination_invoice=destination,
        amount=amount,
    )
    credit.full_clean()
    credit.save()
    recalculate_document_totals(document=destination)
    return credit


@transaction.atomic
def remove_retainer_credit(*, credit):
    credit = InvoiceCredit.objects.select_for_update().select_related("destination_invoice").get(
        pk=credit.pk
    )
    if not credit.destination_invoice.is_editable:
        raise ValidationError("Credits can only be removed from a draft invoice.")
    destination = credit.destination_invoice
    credit.delete()
    recalculate_document_totals(document=destination)
