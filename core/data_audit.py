from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import Decimal

from django.db.models import QuerySet, Sum
from django.utils import timezone

from documents.models import (
    Document,
    DocumentDelivery,
    InvoiceCredit,
    Payment,
    PaymentAdjustment,
    PaymentFeeReconciliationAttempt,
)
from documents.services import money
from projects.models import TimeEntry


@dataclass(frozen=True)
class AuditIssue:
    severity: str
    code: str
    model: str
    object_id: int
    detail: str

    def to_dict(self):
        return asdict(self)


def _documents(company_id=None) -> QuerySet:
    queryset = Document.objects.select_related("project").prefetch_related(
        "line_items",
        "payments",
        "credits_received",
    )
    if company_id is not None:
        queryset = queryset.filter(company_id=company_id)
    return queryset


def _document_issues(document):
    issues = []
    if document.project.company_id != document.company_id:
        issues.append(
            AuditIssue(
                "error",
                "document_company",
                "Document",
                document.pk,
                "Document and project belong to different companies.",
            )
        )

    subtotal = Decimal("0")
    tax_total = Decimal("0")
    for line in document.line_items.all():
        expected_line_total = money(line.rate * line.quantity)
        if line.line_total != expected_line_total:
            issues.append(
                AuditIssue(
                    "error",
                    "line_total",
                    "LineItem",
                    line.pk,
                    f"Stored {line.line_total}; expected {expected_line_total}.",
                )
            )
        subtotal += expected_line_total
        tax_total += money(expected_line_total * line.tax_rate / Decimal("100"))

    subtotal = money(subtotal)
    tax_total = money(tax_total)
    credit_total = money(
        sum((credit.amount for credit in document.credits_received.all()), Decimal("0"))
    )
    total = max(money(subtotal + tax_total - credit_total), Decimal("0.00"))
    expected_totals = {
        "subtotal": subtotal,
        "tax_total": tax_total,
        "credit_total": credit_total,
        "total": total,
    }
    for field, expected in expected_totals.items():
        actual = getattr(document, field)
        if actual != expected:
            issues.append(
                AuditIssue(
                    "error",
                    "document_total",
                    "Document",
                    document.pk,
                    f"{field} is {actual}; expected {expected}.",
                )
            )

    if document.status != Document.Status.DRAFT:
        if not document.number:
            issues.append(
                AuditIssue(
                    "error",
                    "issued_number",
                    "Document",
                    document.pk,
                    "Issued document has no number.",
                )
            )
        if document.sent_at is None:
            issues.append(
                AuditIssue(
                    "error",
                    "issued_timestamp",
                    "Document",
                    document.pk,
                    "Issued document has no sent timestamp.",
                )
            )

    if document.doc_type == Document.Type.INVOICE:
        amount_paid = money(document.amount_paid)
        if amount_paid > document.total:
            issues.append(
                AuditIssue(
                    "error",
                    "invoice_overpaid",
                    "Document",
                    document.pk,
                    f"Net customer payments total {amount_paid}; invoice total is {document.total}.",
                )
            )
        if document.status != Document.Status.VOID:
            if amount_paid > 0 and amount_paid >= document.total:
                expected_status = Document.Status.PAID
            elif amount_paid > 0:
                expected_status = Document.Status.PARTIALLY_PAID
            elif document.viewed_at:
                expected_status = Document.Status.VIEWED
            elif document.sent_at:
                expected_status = Document.Status.SENT
            else:
                expected_status = Document.Status.DRAFT
            if document.status != expected_status:
                issues.append(
                    AuditIssue(
                        "error",
                        "invoice_status",
                        "Document",
                        document.pk,
                        f"Status is {document.status}; payments/timestamps imply {expected_status}.",
                    )
                )
    return issues


def _credit_issues(company_id=None):
    queryset = InvoiceCredit.objects.select_related("source_invoice", "destination_invoice")
    if company_id is not None:
        queryset = queryset.filter(source_invoice__company_id=company_id)
    issues = []
    for credit in queryset:
        source = credit.source_invoice
        destination = credit.destination_invoice
        if source.company_id != destination.company_id:
            issues.append(
                AuditIssue(
                    "error",
                    "credit_company",
                    "InvoiceCredit",
                    credit.pk,
                    "Credit source and destination belong to different companies.",
                )
            )
        if source.project_id != destination.project_id:
            issues.append(
                AuditIssue(
                    "error",
                    "credit_project",
                    "InvoiceCredit",
                    credit.pk,
                    "Credit source and destination belong to different projects.",
                )
            )
        if source.invoice_kind != Document.InvoiceKind.RETAINER:
            issues.append(
                AuditIssue(
                    "error",
                    "credit_source_kind",
                    "InvoiceCredit",
                    credit.pk,
                    "Credit source is not a retainer invoice.",
                )
            )
        if destination.invoice_kind != Document.InvoiceKind.FINAL:
            issues.append(
                AuditIssue(
                    "error",
                    "credit_destination_kind",
                    "InvoiceCredit",
                    credit.pk,
                    "Credit destination is not a final invoice.",
                )
            )
    return issues


def _time_entry_issues(company_id=None):
    queryset = TimeEntry.objects.select_related(
        "project",
        "user",
        "line_item__document",
    )
    if company_id is not None:
        queryset = queryset.filter(company_id=company_id)
    issues = []
    for entry in queryset:
        if entry.project.company_id != entry.company_id or entry.user.company_id != entry.company_id:
            issues.append(
                AuditIssue(
                    "error",
                    "time_company",
                    "TimeEntry",
                    entry.pk,
                    "Time entry, project, and user do not share a company.",
                )
            )
        if entry.status == TimeEntry.Status.INVOICED and entry.line_item_id is None:
            issues.append(
                AuditIssue(
                    "error",
                    "invoiced_time_line",
                    "TimeEntry",
                    entry.pk,
                    "Invoiced time has no invoice line.",
                )
            )
        if entry.line_item_id is not None:
            document = entry.line_item.document
            if entry.status != TimeEntry.Status.INVOICED:
                issues.append(
                    AuditIssue(
                        "error",
                        "attached_time_status",
                        "TimeEntry",
                        entry.pk,
                        "Time attached to an invoice line is not marked invoiced.",
                    )
                )
            if document.doc_type != Document.Type.INVOICE:
                issues.append(
                    AuditIssue(
                        "error",
                        "time_document_type",
                        "TimeEntry",
                        entry.pk,
                        "Time is attached to a non-invoice document.",
                    )
                )
            if document.company_id != entry.company_id or document.project_id != entry.project_id:
                issues.append(
                    AuditIssue(
                        "error",
                        "time_invoice_scope",
                        "TimeEntry",
                        entry.pk,
                        "Time and its invoice line do not share a company and project.",
                    )
                )
    return issues


def _payment_and_adjustment_issues(company_id=None):
    payments = Payment.objects.select_related("document")
    adjustments = PaymentAdjustment.objects.select_related(
        "payment",
        "payment__document",
    )
    fee_attempts = PaymentFeeReconciliationAttempt.objects.select_related(
        "payment",
        "payment__document",
    )
    if company_id is not None:
        payments = payments.filter(document__company_id=company_id)
        adjustments = adjustments.filter(company_id=company_id)
        fee_attempts = fee_attempts.filter(company_id=company_id)
    issues = []
    for payment in payments:
        if payment.document.doc_type != Document.Type.INVOICE:
            issues.append(
                AuditIssue(
                    "error",
                    "payment_document_type",
                    "Payment",
                    payment.pk,
                    "Payment is attached to a non-invoice document.",
                )
            )
        if payment.method == Payment.Method.STRIPE and not payment.stripe_payment_intent_id:
            issues.append(
                AuditIssue(
                    "error",
                    "stripe_payment_intent",
                    "Payment",
                    payment.pk,
                    "Stripe payment has no Payment Intent ID.",
                )
            )
        if payment.fee_pending:
            issues.append(
                AuditIssue(
                    "warning",
                    "stripe_fee_pending",
                    "Payment",
                    payment.pk,
                    "Stripe processing fee is still awaiting reconciliation.",
                )
            )
        if payment.fee_current_amount < 0 or payment.fee_amount < 0:
            issues.append(
                AuditIssue(
                    "error",
                    "payment_fee_negative",
                    "Payment",
                    payment.pk,
                    "Stored processing fee cannot be negative.",
                )
            )
        fee_change_total = payment.adjustments.filter(
            affects_processing_fees=True
        ).aggregate(value=Sum("amount"))["value"] or Decimal("0.00")
        expected_current_fee = money(payment.fee_amount - fee_change_total)
        if payment.fee_current_amount != expected_current_fee:
            issues.append(
                AuditIssue(
                    "error",
                    "payment_fee_marker",
                    "Payment",
                    payment.pk,
                    "Current Stripe fee does not reconcile to the fee adjustment ledger.",
                )
            )
    for adjustment in adjustments:
        if adjustment.payment.document.company_id != adjustment.company_id:
            issues.append(
                AuditIssue(
                    "error",
                    "adjustment_company",
                    "PaymentAdjustment",
                    adjustment.pk,
                    "Adjustment and payment do not share a company.",
                )
            )
        if adjustment.amount == 0:
            issues.append(
                AuditIssue(
                    "error",
                    "adjustment_zero",
                    "PaymentAdjustment",
                    adjustment.pk,
                    "Adjustment amount is zero.",
                )
            )
        fee_types = {
            PaymentAdjustment.Type.FEE_REFUND,
            PaymentAdjustment.Type.FEE_ADJUSTMENT,
        }
        if (adjustment.adjustment_type in fee_types) != adjustment.affects_processing_fees:
            issues.append(
                AuditIssue(
                    "error",
                    "adjustment_fee_classification",
                    "PaymentAdjustment",
                    adjustment.pk,
                    "Processing-fee classification does not match the adjustment type.",
                )
            )
    for attempt in fee_attempts:
        if attempt.payment.document.company_id != attempt.company_id:
            issues.append(
                AuditIssue(
                    "error",
                    "fee_attempt_company",
                    "PaymentFeeReconciliationAttempt",
                    attempt.pk,
                    "Fee reconciliation attempt and payment do not share a company.",
                )
            )
        if (
            attempt.status == PaymentFeeReconciliationAttempt.Status.RESOLVED
            and attempt.observed_fee is None
        ):
            issues.append(
                AuditIssue(
                    "error",
                    "fee_attempt_missing_amount",
                    "PaymentFeeReconciliationAttempt",
                    attempt.pk,
                    "Resolved fee reconciliation attempt has no observed fee.",
                )
            )
    return issues


def _delivery_issues(company_id=None, pending_minutes=15):
    cutoff = timezone.now() - timedelta(minutes=pending_minutes)
    queryset = DocumentDelivery.objects.filter(
        status=DocumentDelivery.Status.PENDING,
        created_at__lt=cutoff,
    )
    if company_id is not None:
        queryset = queryset.filter(document__company_id=company_id)
    return [
        AuditIssue(
            "warning",
            "stale_delivery",
            "DocumentDelivery",
            delivery.pk,
            f"Delivery has remained pending for more than {pending_minutes} minutes.",
        )
        for delivery in queryset
    ]


def audit_data(*, company_id=None, pending_minutes=15):
    issues = []
    for document in _documents(company_id=company_id):
        issues.extend(_document_issues(document))
    issues.extend(_credit_issues(company_id=company_id))
    issues.extend(_time_entry_issues(company_id=company_id))
    issues.extend(_payment_and_adjustment_issues(company_id=company_id))
    issues.extend(
        _delivery_issues(company_id=company_id, pending_minutes=pending_minutes)
    )
    return issues
