import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from clients.models import Contact
from documents.delivery_services import public_document_url, send_document_email
from documents.models import Document, DocumentDelivery, Payment
from documents.proposal_services import sanitize_plain_text, withdraw_proposal
from documents.services import (
    issue_document,
    record_payment,
    release_void_invoice_time,
    void_invoice,
)
from documents.stripe_services import stripe_configuration_status

from .models import AIActionAttempt
from .registry import RegisteredTool, registry


def _object_schema(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _nullable_string(max_length=255):
    return {"type": ["string", "null"], "maxLength": max_length}


def _money(value):
    return f"{Decimal(value):.2f}"


def _parse_money(value, label):
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be a valid amount.") from exc
    if amount <= 0:
        raise ValidationError(f"{label} must be greater than zero.")
    return amount


def _parse_date(value, label):
    if not value:
        return timezone.localdate()
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must use YYYY-MM-DD.") from exc


def _document_link(document):
    name = (
        "proposals:detail"
        if document.doc_type == Document.Type.PROPOSAL
        else "documents:invoice-detail"
    )
    return {
        "label": f"{document.get_doc_type_display()} {document.number}",
        "url": reverse(name, kwargs={"pk": document.pk}),
    }


def _project_link(project):
    return {
        "label": str(project),
        "url": reverse("projects:detail", kwargs={"pk": project.pk}),
    }


def _resolve_document(company, reference, *, statuses=None, doc_type=None):
    reference = reference.strip()
    documents = Document.objects.for_company(company).select_related(
        "project", "project__client", "company"
    )
    if statuses is not None:
        documents = documents.filter(status__in=statuses)
    if doc_type is not None:
        documents = documents.filter(doc_type=doc_type)

    if reference.isdigit():
        by_pk = documents.filter(pk=int(reference)).first()
        if by_pk:
            return by_pk

    exact = list(documents.filter(number__iexact=reference)[:2])
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValidationError("More than one document has that number. Specify proposal or invoice.")

    matches = list(
        documents.filter(
            Q(number__icontains=reference)
            | Q(project__number__icontains=reference)
            | Q(project__name__icontains=reference)
            | Q(project__client__company_name__icontains=reference)
            | Q(project__client__contacts__first_name__icontains=reference)
            | Q(project__client__contacts__last_name__icontains=reference)
        )
        .distinct()
        .order_by("-issue_date", "-pk")[:6]
    )
    if not matches:
        raise ValidationError("No company document matched that reference.")
    if len(matches) > 1:
        choices = ", ".join(
            f"{item.get_doc_type_display()} {item.number} — {item.project.name}"
            for item in matches
        )
        raise ValidationError(f"More than one document matched. Choose one: {choices}.")
    return matches[0]


def _get_recipient(document, contact_id):
    contact = (
        Contact.objects.select_related("client")
        .filter(
            pk=contact_id,
            client=document.project.client,
            client__company=document.company,
        )
        .first()
    )
    if contact is None:
        raise ValidationError("Choose a contact belonging to this document's client.")
    if not contact.email:
        raise ValidationError("The selected contact does not have an email address.")
    return contact


def _document_snapshot(document):
    document = Document.objects.for_company(document.company).get(pk=document.pk)
    lines = list(
        document.line_items.order_by("order", "pk").values(
            "id", "order", "description", "rate", "quantity", "tax_rate", "line_total"
        )
    )
    payments = list(
        document.payments.order_by("pk").values(
            "id", "amount", "method", "received_at", "reference"
        )
    )
    deliveries = list(
        document.deliveries.order_by("pk").values(
            "id",
            "purpose",
            "follow_up_kind",
            "recipient_email",
            "status",
            "subject",
            "created_at",
            "sent_at",
        )
    )
    time_entries = list(
        document.line_items.order_by("pk").values_list("time_entries__id", flat=True)
    )
    payload = {
        "id": document.pk,
        "updated_at": document.updated_at.isoformat(),
        "status": document.status,
        "number": document.number,
        "issue_date": document.issue_date.isoformat(),
        "due_date": document.due_date.isoformat() if document.due_date else None,
        "subtotal": str(document.subtotal),
        "tax_total": str(document.tax_total),
        "credit_total": str(document.credit_total),
        "total": str(document.total),
        "deposit_amount": (
            str(document.deposit_amount)
            if document.deposit_amount is not None
            else None
        ),
        "accept_payments": document.accept_payments,
        "lines": lines,
        "payments": payments,
        "deliveries": deliveries,
        "time_entries": time_entries,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _assert_snapshot(document, expected):
    if _document_snapshot(document) != expected:
        raise ValidationError(
            "The document changed after the AI preview. Review it and prepare a new confirmation."
        )


def _default_subject(document):
    return f"{document.get_doc_type_display()} {document.number} from {document.company.name}"


def _normalize_subject(value, document):
    subject = sanitize_plain_text(value or _default_subject(document)).replace("\n", " ").strip()
    if not subject:
        subject = _default_subject(document)
    return subject[:255]


def _normalize_message(value):
    return sanitize_plain_text(value or "").strip()[:4000]


def _payment_availability(document):
    if document.doc_type != Document.Type.INVOICE:
        return "Not applicable"
    if not document.accept_payments:
        return "Online payment disabled on this invoice"
    if not stripe_configuration_status()["configured"]:
        return "Online payment requested, but Stripe is not configured"
    return "Stripe Pay Now will be available"


def _document_details(document):
    details = [
        f"Document: {document.get_doc_type_display()} {document.number}",
        f"Client: {document.project.client.display_name}",
        f"Project: {document.project.number} — {document.project.name}",
        f"Total: ${document.total:.2f}",
    ]
    if document.doc_type == Document.Type.INVOICE:
        details.extend(
            [
                f"Outstanding balance: ${document.outstanding_balance:.2f}",
                f"Due date: {document.due_date.isoformat() if document.due_date else 'Not set'}",
                f"Payment availability: {_payment_availability(document)}",
            ]
        )
    return details


def get_document_delivery_context(context, arguments):
    document = _resolve_document(context.company, arguments["document_reference"])
    contacts = list(
        document.project.client.contacts.exclude(email="").order_by("-is_primary", "last_name", "first_name")
    )
    deliveries = list(document.deliveries.order_by("-created_at")[:5])
    actions = []
    if document.status == Document.Status.DRAFT:
        actions.extend(["issue", "issue_and_send"])
    elif document.doc_type == Document.Type.PROPOSAL and document.status in {
        Document.Status.SENT,
        Document.Status.VIEWED,
    }:
        actions.extend(["send", "follow_up", "withdraw"])
    elif document.doc_type == Document.Type.INVOICE and document.status in {
        Document.Status.SENT,
        Document.Status.VIEWED,
        Document.Status.PARTIALLY_PAID,
    }:
        actions.extend(["send", "follow_up", "record_manual_payment", "void"])
    if document.doc_type == Document.Type.INVOICE and document.status == Document.Status.VOID:
        actions.append("release_invoiced_time")
    return {
        "document": {
            "id": document.pk,
            "type": document.doc_type,
            "number": document.number,
            "status": document.status,
            "client": document.project.client.display_name,
            "project": f"{document.project.number} — {document.project.name}",
            "total": _money(document.total),
            "outstanding_balance": _money(document.outstanding_balance),
            "due_date": document.due_date.isoformat() if document.due_date else None,
            "payment_availability": _payment_availability(document),
        },
        "contacts": [
            {
                "contact_id": item.pk,
                "name": item.get_full_name(),
                "email": item.email,
                "primary": item.is_primary,
            }
            for item in contacts
        ],
        "recent_deliveries": [
            {
                "recipient": item.recipient_email,
                "status": item.status,
                "sent_at": item.sent_at.isoformat() if item.sent_at else None,
            }
            for item in deliveries
        ],
        "allowed_actions": actions,
        "links": [_document_link(document)],
    }


FOLLOW_UP_KIND_LABELS = {
    DocumentDelivery.FollowUpKind.PROPOSAL: "Proposal follow-up",
    DocumentDelivery.FollowUpKind.RETAINER: "Retainer reminder",
    DocumentDelivery.FollowUpKind.INVOICE: "Invoice reminder",
    DocumentDelivery.FollowUpKind.OVERDUE_INVOICE: "Overdue invoice reminder",
}


def _expected_follow_up_kind(document):
    if document.doc_type == Document.Type.PROPOSAL:
        if document.status not in {Document.Status.SENT, Document.Status.VIEWED}:
            raise ValidationError("Only an open proposal can receive a follow-up.")
        return DocumentDelivery.FollowUpKind.PROPOSAL
    if document.status not in {
        Document.Status.SENT,
        Document.Status.VIEWED,
        Document.Status.PARTIALLY_PAID,
    } or document.outstanding_balance <= 0:
        raise ValidationError("Only an open invoice with a balance can receive a reminder.")
    if document.invoice_kind == Document.InvoiceKind.RETAINER:
        return DocumentDelivery.FollowUpKind.RETAINER
    if document.is_overdue:
        return DocumentDelivery.FollowUpKind.OVERDUE_INVOICE
    return DocumentDelivery.FollowUpKind.INVOICE


def _follow_up_timing(document):
    now = timezone.now()
    anchor = document.viewed_at or document.sent_at
    days_since_activity = None
    if anchor:
        days_since_activity = max((now.date() - timezone.localtime(anchor).date()).days, 0)
    days_overdue = 0
    if document.is_overdue and document.due_date:
        days_overdue = max((timezone.localdate() - document.due_date).days, 0)
    return days_since_activity, days_overdue


def get_document_follow_up_context(context, arguments):
    document = _resolve_document(
        context.company,
        arguments["document_reference"],
        statuses=[
            Document.Status.SENT,
            Document.Status.VIEWED,
            Document.Status.PARTIALLY_PAID,
        ],
    )
    kind = _expected_follow_up_kind(document)
    contacts = list(
        document.project.client.contacts.exclude(email="").order_by(
            "-is_primary", "last_name", "first_name"
        )
    )
    follow_ups = list(
        document.deliveries.filter(
            purpose=DocumentDelivery.Purpose.CLIENT_FOLLOW_UP
        ).order_by("-created_at")[:5]
    )
    last_delivery = (
        document.deliveries.filter(
            purpose__in=[
                DocumentDelivery.Purpose.CLIENT_DOCUMENT,
                DocumentDelivery.Purpose.CLIENT_FOLLOW_UP,
            ]
        )
        .order_by("-created_at")
        .first()
    )
    days_since_activity, days_overdue = _follow_up_timing(document)
    return {
        "document": {
            "id": document.pk,
            "type": document.doc_type,
            "number": document.number,
            "status": document.status,
            "client": document.project.client.display_name,
            "project": f"{document.project.number} — {document.project.name}",
            "total": _money(document.total),
            "outstanding_balance": _money(document.outstanding_balance),
            "due_date": document.due_date.isoformat() if document.due_date else None,
            "sent_at": document.sent_at.isoformat() if document.sent_at else None,
            "viewed_at": document.viewed_at.isoformat() if document.viewed_at else None,
            "days_since_activity": days_since_activity,
            "days_overdue": days_overdue,
        },
        "follow_up_kind": kind,
        "follow_up_label": FOLLOW_UP_KIND_LABELS[kind],
        "eligible_recipients": [
            {
                "contact_id": contact.pk,
                "name": contact.get_full_name(),
                "email": contact.email,
                "primary": contact.is_primary,
            }
            for contact in contacts
        ],
        "last_client_delivery": (
            {
                "purpose": last_delivery.purpose,
                "recipient": last_delivery.recipient_email,
                "status": last_delivery.status,
                "created_at": last_delivery.created_at.isoformat(),
                "sent_at": last_delivery.sent_at.isoformat() if last_delivery.sent_at else None,
            }
            if last_delivery
            else None
        ),
        "recent_follow_ups": [
            {
                "kind": item.follow_up_kind,
                "recipient": item.recipient_email,
                "status": item.status,
                "sent_at": item.sent_at.isoformat() if item.sent_at else None,
            }
            for item in follow_ups
        ],
        "links": [_document_link(document)],
    }


def preview_send_document_follow_up(context, arguments):
    document = _resolve_document(
        context.company,
        arguments["document_reference"],
        statuses=[
            Document.Status.SENT,
            Document.Status.VIEWED,
            Document.Status.PARTIALLY_PAID,
        ],
    )
    expected_kind = _expected_follow_up_kind(document)
    if arguments["follow_up_kind"] != expected_kind:
        raise ValidationError(
            f"This document requires a {FOLLOW_UP_KIND_LABELS[expected_kind].lower()}."
        )
    recipient = _get_recipient(document, arguments["recipient_contact_id"])
    subject = _normalize_subject(arguments["email_subject"], document)
    message = _normalize_message(arguments["email_message"])
    if not message:
        raise ValidationError("A follow-up email requires a client-facing message.")

    latest = (
        document.deliveries.filter(
            purpose=DocumentDelivery.Purpose.CLIENT_FOLLOW_UP,
            status=DocumentDelivery.Status.SENT,
        )
        .order_by("-sent_at", "-pk")
        .first()
    )
    minimum_hours = max(int(getattr(settings, "AI_FOLLOW_UP_MIN_INTERVAL_HOURS", 24)), 1)
    if latest and latest.sent_at and latest.sent_at > timezone.now() - timedelta(hours=minimum_hours):
        raise ValidationError(
            f"A follow-up was already sent within the last {minimum_hours} hours. "
            "Wait before preparing another reminder."
        )

    days_since_activity, days_overdue = _follow_up_timing(document)
    details = [
        *_document_details(document),
        f"Follow-up type: {FOLLOW_UP_KIND_LABELS[expected_kind]}",
        f"Recipient: {recipient.get_full_name()} <{recipient.email}>",
        f"Email subject: {subject}",
        f"Email message: {message}",
    ]
    if days_since_activity is not None:
        details.append(f"Days since last document activity: {days_since_activity}")
    if days_overdue:
        details.append(f"Days overdue: {days_overdue}")
    details.extend(
        [
            "The current public document link will be included.",
            "This sends one email only after final confirmation. It does not schedule or repeat reminders.",
            "A follow-up delivery record will be preserved whether email succeeds or fails.",
        ]
    )
    return {
        "title": FOLLOW_UP_KIND_LABELS[expected_kind],
        "summary": "Review the client-facing reminder before sending it.",
        "details": details,
        "confirm_label": "Send follow-up",
        "revise_prompt": "Revise the follow-up subject or message before sending.",
        "_execution_arguments": {
            "document_id": document.pk,
            "recipient_contact_id": recipient.pk,
            "expected_recipient_name": recipient.get_full_name(),
            "expected_recipient_email": recipient.email.lower(),
            "email_subject": subject,
            "email_message": message,
            "expected_snapshot": _document_snapshot(document),
            "issue_first": False,
            "delivery_purpose": DocumentDelivery.Purpose.CLIENT_FOLLOW_UP,
            "follow_up_kind": expected_kind,
        },
    }


def preview_issue_document(context, arguments):
    document = _resolve_document(
        context.company,
        arguments["document_reference"],
        statuses=[Document.Status.DRAFT],
    )
    if not document.line_items.exists() or document.total <= 0:
        raise ValidationError("Add positive pricing before issuing this document.")
    return {
        "title": f"Issue {document.get_doc_type_display().lower()}",
        "summary": "Issuing activates the public document link. No email will be sent.",
        "details": [*_document_details(document), "Resulting status: Sent"],
        "confirm_label": "Issue document",
        "_execution_arguments": {
            "document_id": document.pk,
            "expected_snapshot": _document_snapshot(document),
        },
    }


@transaction.atomic
def execute_issue_document(context, arguments):
    document = (
        Document.objects.select_for_update()
        .for_company(context.company)
        .get(pk=arguments["document_id"], status=Document.Status.DRAFT)
    )
    _assert_snapshot(document, arguments["expected_snapshot"])
    issued = issue_document(document=document)
    return {
        "message": f"{issued.get_doc_type_display()} {issued.number} issued. Its public link is active; no email was sent.",
        "links": [_document_link(issued)],
        "redirect_url": _document_link(issued)["url"],
    }


def _prepare_delivery(context, arguments, *, issue_first):
    statuses = [Document.Status.DRAFT] if issue_first else [
        Document.Status.SENT,
        Document.Status.VIEWED,
        Document.Status.PARTIALLY_PAID,
    ]
    document = _resolve_document(
        context.company,
        arguments["document_reference"],
        statuses=statuses,
    )
    if issue_first and (not document.line_items.exists() or document.total <= 0):
        raise ValidationError("Add positive pricing before issuing this document.")
    recipient = _get_recipient(document, arguments["recipient_contact_id"])
    subject = _normalize_subject(arguments["email_subject"], document)
    message = _normalize_message(arguments["email_message"])
    action = "Issue and send" if issue_first else "Send"
    details = [
        *_document_details(document),
        f"Recipient: {recipient.get_full_name()} <{recipient.email}>",
        f"Email subject: {subject}",
        f"Email note: {message or 'Standard EZ360PM document email'}",
        f"Resulting status: {'Sent' if issue_first else document.get_status_display()}",
        "A delivery-attempt record will be preserved whether email succeeds or fails.",
    ]
    return {
        "title": f"{action} {document.get_doc_type_display().lower()}",
        "summary": "Final review required. This action activates or uses the public link and emails the selected client contact.",
        "details": details,
        "confirm_label": action,
        "_execution_arguments": {
            "document_id": document.pk,
            "recipient_contact_id": recipient.pk,
            "expected_recipient_name": recipient.get_full_name(),
            "expected_recipient_email": recipient.email.lower(),
            "email_subject": subject,
            "email_message": message,
            "expected_snapshot": _document_snapshot(document),
            "issue_first": issue_first,
            "delivery_purpose": DocumentDelivery.Purpose.CLIENT_DOCUMENT,
            "follow_up_kind": "",
        },
    }


def preview_issue_and_send_document(context, arguments):
    return _prepare_delivery(context, arguments, issue_first=True)


def preview_send_document(context, arguments):
    return _prepare_delivery(context, arguments, issue_first=False)


def execute_document_delivery(context, arguments):
    expected_statuses = [Document.Status.DRAFT] if arguments["issue_first"] else [
        Document.Status.SENT,
        Document.Status.VIEWED,
        Document.Status.PARTIALLY_PAID,
    ]
    with transaction.atomic():
        document = (
            Document.objects.select_for_update()
            .for_company(context.company)
            .select_related("company", "project", "project__client")
            .get(pk=arguments["document_id"], status__in=expected_statuses)
        )
        _assert_snapshot(document, arguments["expected_snapshot"])
        recipient = _get_recipient(document, arguments["recipient_contact_id"])
        if (
            recipient.get_full_name() != arguments["expected_recipient_name"]
            or recipient.email.lower() != arguments["expected_recipient_email"]
        ):
            raise ValidationError(
                "The selected recipient changed after the AI preview. Prepare a new confirmation."
            )
        if arguments["issue_first"]:
            document = issue_document(document=document)

    # Email is intentionally outside the database transaction. The issued
    # document remains committed if the provider fails, and the delivery service
    # preserves a failed attempt for manual follow-up.
    delivery = send_document_email(
        document=document,
        recipient_name=recipient.get_full_name(),
        recipient_email=recipient.email,
        document_url=public_document_url(document),
        subject=arguments["email_subject"],
        message=arguments["email_message"],
        purpose=arguments.get(
            "delivery_purpose", DocumentDelivery.Purpose.CLIENT_DOCUMENT
        ),
        follow_up_kind=arguments.get("follow_up_kind", ""),
    )
    if delivery.status == delivery.Status.SENT:
        message = f"{document.get_doc_type_display()} {document.number} sent to {delivery.recipient_email}."
    else:
        message = (
            f"{document.get_doc_type_display()} {document.number} was issued, but the email failed: "
            f"{delivery.failure_message}"
            if arguments["issue_first"]
            else f"Email failed: {delivery.failure_message}"
        )
    return {
        "message": message,
        "links": [_document_link(document)],
        "redirect_url": _document_link(document)["url"],
        "delivery_status": delivery.status,
        "delivery_id": delivery.pk,
    }


def preview_withdraw_proposal(context, arguments):
    proposal = _resolve_document(
        context.company,
        arguments["proposal_reference"],
        statuses=[Document.Status.SENT, Document.Status.VIEWED],
        doc_type=Document.Type.PROPOSAL,
    )
    return {
        "title": "Withdraw proposal",
        "summary": "The client link will remain as history but the proposal can no longer be accepted.",
        "details": [*_document_details(proposal), "Resulting status: Withdrawn"],
        "confirm_label": "Withdraw proposal",
        "_execution_arguments": {
            "document_id": proposal.pk,
            "expected_snapshot": _document_snapshot(proposal),
        },
    }


@transaction.atomic
def execute_withdraw_proposal(context, arguments):
    proposal = (
        Document.objects.select_for_update()
        .for_company(context.company)
        .get(
            pk=arguments["document_id"],
            doc_type=Document.Type.PROPOSAL,
            status__in=[Document.Status.SENT, Document.Status.VIEWED],
        )
    )
    _assert_snapshot(proposal, arguments["expected_snapshot"])
    proposal = withdraw_proposal(proposal=proposal)
    return {
        "message": f"Proposal {proposal.number} withdrawn.",
        "links": [_document_link(proposal)],
        "redirect_url": _document_link(proposal)["url"],
    }


def preview_void_invoice(context, arguments):
    invoice = _resolve_document(
        context.company,
        arguments["invoice_reference"],
        statuses=[Document.Status.SENT, Document.Status.VIEWED, Document.Status.PARTIALLY_PAID],
        doc_type=Document.Type.INVOICE,
    )
    reason = sanitize_plain_text(arguments["reason"] or "").strip()[:1000]
    if invoice.amount_paid > 0:
        raise ValidationError("An invoice with recorded payments cannot be voided through the assistant.")
    return {
        "title": "Void invoice",
        "summary": "Voiding removes the invoice from outstanding balances but preserves its financial history.",
        "details": [
            *_document_details(invoice),
            f"Reason: {reason or 'No reason supplied'}",
            "Attached time remains invoiced until separately released.",
            "Resulting status: Void",
        ],
        "confirm_label": "Void invoice",
        "_execution_arguments": {
            "document_id": invoice.pk,
            "reason": reason,
            "expected_snapshot": _document_snapshot(invoice),
        },
    }


@transaction.atomic
def execute_void_invoice(context, arguments):
    invoice = (
        Document.objects.select_for_update()
        .for_company(context.company)
        .get(
            pk=arguments["document_id"],
            doc_type=Document.Type.INVOICE,
            status__in=[Document.Status.SENT, Document.Status.VIEWED, Document.Status.PARTIALLY_PAID],
        )
    )
    _assert_snapshot(invoice, arguments["expected_snapshot"])
    if invoice.amount_paid > 0:
        raise ValidationError("The invoice received a payment after the preview and cannot be voided.")
    invoice = void_invoice(invoice=invoice, reason=arguments["reason"])
    return {
        "message": f"Invoice {invoice.number} voided. Attached time remains invoiced.",
        "links": [_document_link(invoice)],
        "redirect_url": _document_link(invoice)["url"],
    }


def preview_record_manual_payment(context, arguments):
    invoice = _resolve_document(
        context.company,
        arguments["invoice_reference"],
        statuses=[Document.Status.SENT, Document.Status.VIEWED, Document.Status.PARTIALLY_PAID],
        doc_type=Document.Type.INVOICE,
    )
    amount = _parse_money(arguments["amount"], "Payment amount")
    if amount > invoice.outstanding_balance:
        raise ValidationError("Payment cannot exceed the outstanding balance.")
    method = arguments["method"]
    if method not in {Payment.Method.CHECK, Payment.Method.CASH, Payment.Method.OTHER}:
        raise ValidationError("Assistant-entered payments must be check, cash, or other.")
    received_at = _parse_date(arguments["received_at"], "Received date")
    reference = sanitize_plain_text(arguments["reference"] or "").strip()[:255]
    remaining = invoice.outstanding_balance - amount
    resulting = "Paid" if remaining == 0 else "Partially paid"
    return {
        "title": "Record manual payment",
        "summary": "This adds revenue and changes the invoice balance. Confirm against the actual payment received.",
        "details": [
            *_document_details(invoice),
            f"Payment: ${amount:.2f}",
            f"Method: {Payment.Method(method).label}",
            f"Received: {received_at.isoformat()}",
            f"Reference: {reference or 'None'}",
            f"Balance after payment: ${remaining:.2f}",
            f"Resulting status: {resulting}",
        ],
        "confirm_label": "Record payment",
        "_execution_arguments": {
            "document_id": invoice.pk,
            "amount": str(amount),
            "method": method,
            "received_at": received_at.isoformat(),
            "reference": reference,
            "expected_snapshot": _document_snapshot(invoice),
        },
    }


@transaction.atomic
def execute_record_manual_payment(context, arguments):
    invoice = (
        Document.objects.select_for_update()
        .for_company(context.company)
        .get(
            pk=arguments["document_id"],
            doc_type=Document.Type.INVOICE,
            status__in=[Document.Status.SENT, Document.Status.VIEWED, Document.Status.PARTIALLY_PAID],
        )
    )
    _assert_snapshot(invoice, arguments["expected_snapshot"])
    payment = record_payment(
        invoice=invoice,
        payment_data={
            "amount": Decimal(arguments["amount"]),
            "method": arguments["method"],
            "received_at": date.fromisoformat(arguments["received_at"]),
            "reference": arguments["reference"],
        },
    )
    invoice.refresh_from_db()
    return {
        "message": f"${payment.amount:.2f} {payment.get_method_display().lower()} payment recorded for invoice {invoice.number}.",
        "links": [_document_link(invoice)],
        "redirect_url": _document_link(invoice)["url"],
        "refresh_page": True,
    }


def preview_release_invoice_time(context, arguments):
    invoice = _resolve_document(
        context.company,
        arguments["invoice_reference"],
        statuses=[Document.Status.VOID],
        doc_type=Document.Type.INVOICE,
    )
    entries = list(
        invoice.line_items.filter(time_entries__isnull=False)
        .values_list("time_entries__id", "time_entries__description")
        .distinct()
    )
    if not entries:
        raise ValidationError("This void invoice has no attached time to release.")
    return {
        "title": "Release time from void invoice",
        "summary": "Released entries become eligible for billing again. The void invoice remains unchanged.",
        "details": [
            *_document_details(invoice),
            f"Time entries to release: {len(entries)}",
            "Risk: these entries can be included on another invoice after release.",
        ],
        "confirm_label": "Release time",
        "_execution_arguments": {
            "document_id": invoice.pk,
            "expected_snapshot": _document_snapshot(invoice),
            "expected_entry_ids": sorted(item[0] for item in entries),
        },
    }


@transaction.atomic
def execute_release_invoice_time(context, arguments):
    invoice = (
        Document.objects.select_for_update()
        .for_company(context.company)
        .get(
            pk=arguments["document_id"],
            doc_type=Document.Type.INVOICE,
            status=Document.Status.VOID,
        )
    )
    _assert_snapshot(invoice, arguments["expected_snapshot"])
    current_ids = sorted(
        invoice.line_items.filter(time_entries__isnull=False)
        .values_list("time_entries__id", flat=True)
        .distinct()
    )
    if current_ids != arguments["expected_entry_ids"]:
        raise ValidationError("The invoice's attached time changed after the preview.")
    count = release_void_invoice_time(invoice=invoice)
    return {
        "message": f"Released {count} time entr{'y' if count == 1 else 'ies'} from void invoice {invoice.number}.",
        "links": [_document_link(invoice), _project_link(invoice.project)],
        "redirect_url": _document_link(invoice)["url"],
    }


DELIVERY_SCHEMA = _object_schema(
    {
        "document_reference": {"type": "string", "minLength": 1, "maxLength": 255},
        "recipient_contact_id": {"type": "integer", "minimum": 1},
        "email_subject": _nullable_string(255),
        "email_message": _nullable_string(4000),
    }
)

registry.register(
    RegisteredTool(
        "get_document_delivery_context",
        "Read a company-scoped proposal or invoice, its eligible client contacts, delivery history, totals, and allowed consequential actions before preparing issue, send, payment, void, withdrawal, or time-release work.",
        _object_schema(
            {"document_reference": {"type": "string", "minLength": 1, "maxLength": 255}}
        ),
        get_document_delivery_context,
    )
)
registry.register(
    RegisteredTool(
        "get_document_follow_up_context",
        "Read one open proposal or invoice, its timing, balance, prior follow-ups, and eligible client contacts before drafting a manual reminder.",
        _object_schema(
            {"document_reference": {"type": "string", "minLength": 1, "maxLength": 255}}
        ),
        get_document_follow_up_context,
    )
)
registry.register(
    RegisteredTool(
        "send_document_follow_up",
        "Prepare one manual proposal, retainer, invoice, or overdue-invoice follow-up email. It never schedules or repeats and requires final confirmation before sending.",
        _object_schema(
            {
                "document_reference": {"type": "string", "minLength": 1, "maxLength": 255},
                "follow_up_kind": {
                    "type": "string",
                    "enum": ["proposal", "retainer", "invoice", "overdue_invoice"],
                },
                "recipient_contact_id": {"type": "integer", "minimum": 1},
                "email_subject": _nullable_string(255),
                "email_message": {"type": "string", "minLength": 1, "maxLength": 4000},
            }
        ),
        preview_send_document_follow_up,
        risk_level=AIActionAttempt.RiskLevel.EXTERNAL_COMMIT,
        executor=execute_document_delivery,
    )
)
registry.register(
    RegisteredTool(
        "issue_document",
        "Prepare issuing a reviewed draft without emailing it. Issuing activates the public client link and requires final confirmation.",
        _object_schema(
            {"document_reference": {"type": "string", "minLength": 1, "maxLength": 255}}
        ),
        preview_issue_document,
        risk_level=AIActionAttempt.RiskLevel.EXTERNAL_COMMIT,
        executor=execute_issue_document,
    )
)
registry.register(
    RegisteredTool(
        "issue_and_send_document",
        "Prepare issuing a reviewed draft and emailing exactly one selected contact belonging to the document client. Requires final confirmation.",
        DELIVERY_SCHEMA,
        preview_issue_and_send_document,
        risk_level=AIActionAttempt.RiskLevel.EXTERNAL_COMMIT,
        executor=execute_document_delivery,
    )
)
registry.register(
    RegisteredTool(
        "send_document",
        "Prepare emailing an already-issued open proposal or invoice to exactly one selected client contact. Requires final confirmation.",
        DELIVERY_SCHEMA,
        preview_send_document,
        risk_level=AIActionAttempt.RiskLevel.EXTERNAL_COMMIT,
        executor=execute_document_delivery,
    )
)
registry.register(
    RegisteredTool(
        "withdraw_proposal",
        "Prepare withdrawing an open proposal. The proposal can no longer be accepted after confirmation.",
        _object_schema(
            {"proposal_reference": {"type": "string", "minLength": 1, "maxLength": 255}}
        ),
        preview_withdraw_proposal,
        risk_level=AIActionAttempt.RiskLevel.EXTERNAL_COMMIT,
        executor=execute_withdraw_proposal,
    )
)
registry.register(
    RegisteredTool(
        "void_invoice",
        "Prepare voiding an unpaid open invoice while preserving history. Invoices with recorded payments are blocked.",
        _object_schema(
            {
                "invoice_reference": {"type": "string", "minLength": 1, "maxLength": 255},
                "reason": _nullable_string(1000),
            }
        ),
        preview_void_invoice,
        risk_level=AIActionAttempt.RiskLevel.EXTERNAL_COMMIT,
        executor=execute_void_invoice,
    )
)
registry.register(
    RegisteredTool(
        "record_manual_payment",
        "Prepare recording a verified check, cash, or other manual payment on an issued invoice. Never use this for Stripe or inferred payments.",
        _object_schema(
            {
                "invoice_reference": {"type": "string", "minLength": 1, "maxLength": 255},
                "amount": {"type": "number", "exclusiveMinimum": 0},
                "method": {"type": "string", "enum": ["check", "cash", "other"]},
                "received_at": _nullable_string(10),
                "reference": _nullable_string(255),
            }
        ),
        preview_record_manual_payment,
        risk_level=AIActionAttempt.RiskLevel.EXTERNAL_COMMIT,
        executor=execute_record_manual_payment,
    )
)
registry.register(
    RegisteredTool(
        "release_void_invoice_time",
        "Prepare releasing time entries attached to a void invoice so they can be billed again. Requires final confirmation.",
        _object_schema(
            {"invoice_reference": {"type": "string", "minLength": 1, "maxLength": 255}}
        ),
        preview_release_invoice_time,
        risk_level=AIActionAttempt.RiskLevel.EXTERNAL_COMMIT,
        executor=execute_release_invoice_time,
    )
)
