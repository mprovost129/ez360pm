from collections import defaultdict
from copy import deepcopy
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from accounts.models import Company
from projects.models import Project, TimeEntry

from .models import Document, DocumentNumberSequence, LineItem, Payment

CENT = Decimal("0.01")


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def allocate_document_number(*, company, doc_type, on_date=None):
    local_date = on_date or timezone.localdate()
    period = local_date.strftime("%y")
    prefix = "I" if doc_type == Document.Type.INVOICE else "P"
    with transaction.atomic():
        locked_company = Company.objects.select_for_update().get(pk=company.pk)
        sequence, _created = DocumentNumberSequence.objects.get_or_create(
            company=locked_company,
            doc_type=doc_type,
            period=period,
        )
        sequence.last_value += 1
        sequence.save(update_fields=["last_value"])
        return f"{prefix}-{period}-{sequence.last_value:04d}"


@transaction.atomic
def recalculate_document_totals(*, document):
    document = Document.objects.select_for_update().get(pk=document.pk)
    subtotal = Decimal("0")
    tax_total = Decimal("0")
    for line in document.line_items.select_for_update():
        line_total = money(line.rate * line.quantity)
        if line.line_total != line_total:
            line.line_total = line_total
            line.save(update_fields=["line_total"])
        subtotal += line_total
        tax_total += money(line_total * line.tax_rate / Decimal("100"))

    credit_total = document.credits_received.aggregate(value=Sum("amount"))["value"]
    credit_total = money(credit_total or Decimal("0"))
    subtotal = money(subtotal)
    tax_total = money(tax_total)
    total = max(money(subtotal + tax_total - credit_total), Decimal("0.00"))
    document.subtotal = subtotal
    document.tax_total = tax_total
    document.credit_total = credit_total
    document.total = total
    document.save(update_fields=["subtotal", "tax_total", "credit_total", "total", "updated_at"])
    return document


@transaction.atomic
def create_invoice(*, company, project, invoice_data):
    try:
        project = Project.objects.for_company(company).get(pk=project.pk)
    except Project.DoesNotExist:
        raise ValidationError("Project must belong to the company.") from None

    data = dict(invoice_data)
    number = data.pop("number", "").strip() or allocate_document_number(
        company=company,
        doc_type=Document.Type.INVOICE,
        on_date=data.get("issue_date"),
    )
    invoice = Document(
        company=company,
        project=project,
        doc_type=Document.Type.INVOICE,
        number=number,
        **data,
    )
    invoice.full_clean()
    invoice.save()

    if (
        project.billing_type == Project.BillingType.FLAT_FEE
        and invoice.invoice_kind == Document.InvoiceKind.FINAL
    ):
        LineItem.objects.create(
            document=invoice,
            order=1,
            description=project.name,
            rate=project.fixed_fee,
            quantity=Decimal("1.00"),
            tax_rate=Decimal("0"),
            line_total=money(project.fixed_fee),
        )
    return recalculate_document_totals(document=invoice)


def _require_draft(document):
    if document.status != Document.Status.DRAFT:
        raise ValidationError("Only draft documents can be edited.")


@transaction.atomic
def duplicate_document(*, document):
    document = (
        Document.objects.select_for_update()
        .select_related("company", "project")
        .prefetch_related("line_items")
        .get(pk=document.pk)
    )
    if document.doc_type == Document.Type.INVOICE and not document.is_editable:
        raise ValidationError("Only draft invoices can be duplicated.")
    if document.doc_type not in {Document.Type.INVOICE, Document.Type.PROPOSAL}:
        raise ValidationError("This document cannot be duplicated.")

    today = timezone.localdate()
    duplicate = Document.objects.create(
        company=document.company,
        project=document.project,
        doc_type=document.doc_type,
        invoice_kind=document.invoice_kind,
        number=allocate_document_number(
            company=document.company,
            doc_type=document.doc_type,
            on_date=today,
        ),
        status=Document.Status.DRAFT,
        issue_date=today,
        due_date=(
            today + timedelta(days=document.company.default_invoice_due_days)
            if document.doc_type == Document.Type.INVOICE
            else None
        ),
        body_sections=deepcopy(document.body_sections),
        terms=document.terms,
        notes=document.notes,
        accept_payments=(
            document.accept_payments
            if document.doc_type == Document.Type.INVOICE
            else False
        ),
    )
    LineItem.objects.bulk_create(
        [
            LineItem(
                document=duplicate,
                order=line.order,
                description=line.description,
                rate=line.rate,
                quantity=line.quantity,
                tax_rate=line.tax_rate,
                line_total=line.line_total,
            )
            for line in document.line_items.all()
        ]
    )
    return recalculate_document_totals(document=duplicate)


@transaction.atomic
def save_line_item(*, document, line_data, line=None):
    document = Document.objects.select_for_update().get(pk=document.pk)
    _require_draft(document)
    if line is None:
        order = document.line_items.aggregate(value=Max("order"))["value"] or 0
        line = LineItem(document=document, order=order + 1)
    elif line.document_id != document.pk:
        raise ValidationError("Line item does not belong to this document.")
    for field, value in line_data.items():
        setattr(line, field, value)
    line.line_total = money(line.rate * line.quantity)
    line.full_clean()
    line.save()
    recalculate_document_totals(document=document)
    return line


@transaction.atomic
def delete_line_item(*, line):
    line = LineItem.objects.select_for_update().select_related("document").get(pk=line.pk)
    document = Document.objects.select_for_update().get(pk=line.document_id)
    _require_draft(document)
    line.time_entries.update(line_item=None, status=TimeEntry.Status.LOGGED)
    line.delete()
    recalculate_document_totals(document=document)


@transaction.atomic
def move_line_item(*, document, line, direction):
    document = Document.objects.select_for_update().get(pk=document.pk)
    _require_draft(document)
    lines = list(document.line_items.select_for_update().order_by("order", "pk"))
    try:
        index = next(index for index, candidate in enumerate(lines) if candidate.pk == line.pk)
    except StopIteration:
        raise ValidationError("Line item does not belong to this document.") from None
    offset = {"up": -1, "down": 1}.get(direction)
    if offset is None:
        raise ValidationError("Unknown line movement direction.")
    target_index = index + offset
    if target_index < 0 or target_index >= len(lines):
        return lines[index]

    moving = lines[index]
    target = lines[target_index]
    moving_order = moving.order
    target_order = target.order
    temporary_order = max(candidate.order for candidate in lines) + 1
    moving.order = temporary_order
    moving.save(update_fields=["order"])
    target.order = moving_order
    target.save(update_fields=["order"])
    moving.order = target_order
    moving.save(update_fields=["order"])
    return moving


@transaction.atomic
def attach_time_to_invoice(*, invoice, entries, grouping):
    invoice = Document.objects.select_for_update().select_related("project").get(pk=invoice.pk)
    _require_draft(invoice)
    if invoice.doc_type != Document.Type.INVOICE:
        raise ValidationError("Time can only be attached to an invoice.")
    if invoice.project.billing_type != Project.BillingType.HOURLY:
        raise ValidationError("Only hourly projects generate invoice lines from time.")

    requested_ids = {entry.pk for entry in entries}
    locked_entries = list(
        TimeEntry.objects.select_for_update()
        .filter(
            pk__in=requested_ids,
            company=invoice.company,
            project=invoice.project,
            user__company=invoice.company,
            end_time__isnull=False,
            billable=True,
            status=TimeEntry.Status.LOGGED,
            line_item__isnull=True,
        )
        .order_by("start_time", "pk")
    )
    if len(locked_entries) != len(requested_ids) or not locked_entries:
        raise ValidationError("One or more selected time entries are no longer billable.")
    if grouping not in {"individual", "description", "combined"}:
        raise ValidationError("Unknown time grouping option.")

    groups = []
    if grouping == "individual":
        groups = [([entry], entry.description or "Professional services") for entry in locked_entries]
    elif grouping == "description":
        by_description = defaultdict(list)
        for entry in locked_entries:
            by_description[entry.description.strip() or "Professional services"].append(entry)
        groups = [(group, description) for description, group in by_description.items()]
    else:
        groups = [(locked_entries, "Professional services")]

    next_order = invoice.line_items.aggregate(value=Max("order"))["value"] or 0
    for grouped_entries, description in groups:
        next_order += 1
        quantity = sum((entry.duration_hours for entry in grouped_entries), Decimal("0"))
        line = LineItem.objects.create(
            document=invoice,
            order=next_order,
            description=description,
            rate=invoice.project.hourly_rate,
            quantity=quantity,
            tax_rate=Decimal("0"),
            line_total=money(invoice.project.hourly_rate * quantity),
        )
        TimeEntry.objects.filter(pk__in=[entry.pk for entry in grouped_entries]).update(
            line_item=line,
            status=TimeEntry.Status.INVOICED,
        )
    return recalculate_document_totals(document=invoice)


@transaction.atomic
def delete_draft_document(*, document):
    document = Document.objects.select_for_update().get(pk=document.pk)
    _require_draft(document)
    TimeEntry.objects.filter(line_item__document=document).update(
        line_item=None,
        status=TimeEntry.Status.LOGGED,
    )
    document.delete()


@transaction.atomic
def release_void_invoice_time(*, invoice):
    invoice = Document.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != Document.Status.VOID:
        raise ValidationError("Explicit release is only available for void invoices.")
    count = TimeEntry.objects.filter(line_item__document=invoice).update(
        line_item=None,
        status=TimeEntry.Status.LOGGED,
    )
    return count


@transaction.atomic
def issue_document(*, document, at=None):
    document = Document.objects.select_for_update().get(pk=document.pk)
    _require_draft(document)
    recalculate_document_totals(document=document)
    document.refresh_from_db()
    if not document.line_items.exists() or document.total <= 0:
        raise ValidationError("Add positive pricing before issuing this document.")
    document.status = Document.Status.SENT
    document.sent_at = at or timezone.now()
    document.full_clean()
    document.save(update_fields=["status", "sent_at", "updated_at"])
    return document


@transaction.atomic
def record_public_view(*, document, at=None):
    document = Document.objects.select_for_update().get(pk=document.pk)
    if document.status == Document.Status.DRAFT:
        raise ValidationError("Draft documents are not public.")
    if document.viewed_at is None:
        document.viewed_at = at or timezone.now()
        fields = ["viewed_at", "updated_at"]
        if document.status == Document.Status.SENT:
            document.status = Document.Status.VIEWED
            fields.append("status")
        document.save(update_fields=fields)
    return document


@transaction.atomic
def void_invoice(*, invoice, reason, at=None):
    invoice = Document.objects.select_for_update().get(pk=invoice.pk)
    if invoice.doc_type != Document.Type.INVOICE:
        raise ValidationError("Only invoices can be voided.")
    if invoice.status in {Document.Status.DRAFT, Document.Status.PAID, Document.Status.VOID}:
        raise ValidationError("This invoice cannot be voided.")
    invoice.status = Document.Status.VOID
    invoice.void_reason = reason.strip()
    invoice.voided_at = at or timezone.now()
    invoice.save(update_fields=["status", "void_reason", "voided_at", "updated_at"])
    return invoice


def _status_without_payment(invoice):
    if invoice.viewed_at:
        return Document.Status.VIEWED
    if invoice.sent_at:
        return Document.Status.SENT
    return Document.Status.DRAFT


@transaction.atomic
def recalculate_payment_status(*, invoice):
    invoice = Document.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status == Document.Status.VOID:
        return invoice
    amount_paid = invoice.payments.aggregate(value=Sum("amount"))["value"] or Decimal("0")
    if amount_paid > 0 and amount_paid >= invoice.total:
        status = Document.Status.PAID
    elif amount_paid > 0:
        status = Document.Status.PARTIALLY_PAID
    else:
        status = _status_without_payment(invoice)
    if invoice.status != status:
        invoice.status = status
        invoice.save(update_fields=["status", "updated_at"])
    return invoice


@transaction.atomic
def record_payment(*, invoice, payment_data, allow_overpayment=False):
    invoice = Document.objects.select_for_update().get(pk=invoice.pk)
    if invoice.doc_type != Document.Type.INVOICE or invoice.status in {
        Document.Status.DRAFT,
        Document.Status.VOID,
    }:
        raise ValidationError("Payments require an issued, non-void invoice.")
    intent_id = payment_data.get("stripe_payment_intent_id")
    if intent_id:
        existing = Payment.objects.filter(stripe_payment_intent_id=intent_id).first()
        if existing:
            if existing.document_id != invoice.pk:
                raise ValidationError("Payment intent is already linked to another invoice.")
            return existing
    amount = money(payment_data["amount"])
    # Manual entry rejects overpayment to catch data-entry mistakes. A verified
    # external capture (Stripe) passes allow_overpayment=True: the money is real
    # and must be recorded even if the balance dropped after the payment was
    # authorized, leaving the invoice overpaid for data_audit to surface.
    if not allow_overpayment and amount > invoice.outstanding_balance:
        raise ValidationError("Payment cannot exceed the outstanding balance.")
    payment = Payment(document=invoice, **payment_data)
    payment.amount = amount
    payment.full_clean()
    payment.save()
    invoice = recalculate_payment_status(invoice=invoice)
    from projects.workflow import activate_project_if_funded

    activate_project_if_funded(invoice=invoice)
    return payment


@transaction.atomic
def update_payment(*, payment, payment_data):
    payment = Payment.objects.select_for_update().select_related("document").get(pk=payment.pk)
    invoice = Document.objects.select_for_update().get(pk=payment.document_id)
    other_paid = invoice.payments.exclude(pk=payment.pk).aggregate(value=Sum("amount"))["value"] or Decimal("0")
    amount = money(payment_data["amount"])
    if other_paid + amount > invoice.total:
        raise ValidationError("Payments cannot exceed the invoice total.")
    for field, value in payment_data.items():
        setattr(payment, field, value)
    payment.amount = amount
    payment.full_clean()
    payment.save()
    invoice = recalculate_payment_status(invoice=invoice)
    from projects.workflow import activate_project_if_funded

    activate_project_if_funded(invoice=invoice)
    return payment


@transaction.atomic
def delete_payment(*, payment):
    payment = Payment.objects.select_for_update().select_related("document").get(pk=payment.pk)
    invoice = payment.document
    payment.delete()
    recalculate_payment_status(invoice=invoice)
