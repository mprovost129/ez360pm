import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q, Sum
from django.utils import timezone

from accounts.models import Company, CompanyOwnedModel
from projects.models import Project


class Document(CompanyOwnedModel):
    class Type(models.TextChoices):
        PROPOSAL = "proposal", "Proposal"
        INVOICE = "invoice", "Invoice"

    class InvoiceKind(models.TextChoices):
        RETAINER = "retainer", "Retainer"
        FINAL = "final", "Final"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        VIEWED = "viewed", "Viewed"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        WITHDRAWN = "withdrawn", "Withdrawn"
        PARTIALLY_PAID = "partially_paid", "Partially paid"
        PAID = "paid", "Paid"
        VOID = "void", "Void"

    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="documents",
    )
    doc_type = models.CharField(max_length=20, choices=Type.choices)
    invoice_kind = models.CharField(
        max_length=20,
        choices=InvoiceKind.choices,
        blank=True,
    )
    source_proposal = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="derived_invoices",
        blank=True,
        null=True,
    )
    number = models.CharField(max_length=30)
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    issue_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField(blank=True, null=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    credit_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    body_sections = models.JSONField(default=list, blank=True)
    terms = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    accept_payments = models.BooleanField(default=False)
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    sent_at = models.DateTimeField(blank=True, null=True)
    viewed_at = models.DateTimeField(blank=True, null=True)
    responded_at = models.DateTimeField(blank=True, null=True)
    accepted_by_name = models.CharField(max_length=255, blank=True)
    accepted_by_email = models.EmailField(blank=True)
    accepted_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
    )
    acceptance_ip = models.GenericIPAddressField(blank=True, null=True)
    voided_at = models.DateTimeField(blank=True, null=True)
    void_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-issue_date", "-number", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("company", "doc_type", "number"),
                name="documents_company_type_number_unique",
            ),
            models.CheckConstraint(
                condition=(
                    Q(doc_type="invoice", due_date__isnull=False)
                    | Q(doc_type="proposal", due_date__isnull=True)
                ),
                name="documents_due_date_matches_type",
            ),
            models.CheckConstraint(
                condition=(
                    Q(doc_type="invoice", invoice_kind__in=("retainer", "final"))
                    | Q(doc_type="proposal", invoice_kind="")
                ),
                name="documents_kind_matches_type",
            ),
        ]
        indexes = [
            models.Index(fields=("company", "doc_type", "status")),
            models.Index(fields=("company", "project", "doc_type")),
            models.Index(fields=("company", "due_date")),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.project_id and self.project.company_id != self.company_id:
            errors["project"] = "Project must belong to the same company."
        if self.doc_type == self.Type.INVOICE:
            if not self.invoice_kind:
                errors["invoice_kind"] = "Invoices require an invoice kind."
            if self.due_date is None:
                errors["due_date"] = "Invoices require a due date."
            allowed = {
                self.Status.DRAFT,
                self.Status.SENT,
                self.Status.VIEWED,
                self.Status.PARTIALLY_PAID,
                self.Status.PAID,
                self.Status.VOID,
            }
        else:
            if self.invoice_kind:
                errors["invoice_kind"] = "Proposals cannot have an invoice kind."
            if self.due_date is not None:
                errors["due_date"] = "Proposals cannot have a due date."
            allowed = {
                self.Status.DRAFT,
                self.Status.SENT,
                self.Status.VIEWED,
                self.Status.ACCEPTED,
                self.Status.DECLINED,
                self.Status.WITHDRAWN,
            }
        if self.status not in allowed:
            errors["status"] = "Status is not valid for this document type."
        if self.source_proposal_id:
            if self.source_proposal.doc_type != self.Type.PROPOSAL:
                errors["source_proposal"] = "Source document must be a proposal."
            elif self.source_proposal.project_id != self.project_id:
                errors["source_proposal"] = "Source proposal must use the same project."
        if errors:
            raise ValidationError(errors)

    @property
    def amount_paid(self):
        return self.payments.aggregate(value=Sum("amount"))["value"] or Decimal("0.00")

    @property
    def outstanding_balance(self):
        return max(self.total - self.amount_paid, Decimal("0.00"))

    @property
    def is_overdue(self):
        return (
            self.doc_type == self.Type.INVOICE
            and self.status != self.Status.VOID
            and self.outstanding_balance > 0
            and self.due_date is not None
            and self.due_date < timezone.localdate()
        )

    @property
    def is_editable(self):
        return self.status == self.Status.DRAFT

    def __str__(self):
        return f"{self.number} - {self.get_doc_type_display()}"


class LineItem(models.Model):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="line_items",
    )
    order = models.PositiveIntegerField(default=0)
    description = models.CharField(max_length=255)
    rate = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0"))],
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    tax_rate = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ("order", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("document", "order"),
                name="documents_line_order_unique",
            ),
            models.CheckConstraint(
                condition=Q(rate__gte=0) & Q(quantity__gt=0) & Q(tax_rate__gte=0),
                name="documents_line_values_nonnegative",
            ),
        ]

    def __str__(self):
        return self.description


class Payment(models.Model):
    class Method(models.TextChoices):
        STRIPE = "stripe", "Stripe"
        CHECK = "check", "Check"
        CASH = "cash", "Cash"
        OTHER = "other", "Other"

    document = models.ForeignKey(
        Document,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    method = models.CharField(max_length=20, choices=Method.choices)
    received_at = models.DateField(default=timezone.localdate)
    reference = models.CharField(max_length=255, blank=True)
    stripe_payment_intent_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        unique=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-received_at", "-created_at", "-pk")
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="documents_payment_amount_positive",
            )
        ]
        indexes = [models.Index(fields=("document", "received_at"))]

    def clean(self):
        super().clean()
        if self.document_id and self.document.doc_type != Document.Type.INVOICE:
            raise ValidationError({"document": "Payments require an invoice."})

    def __str__(self):
        return f"{self.get_method_display()} payment of {self.amount}"


class InvoiceCredit(models.Model):
    source_invoice = models.ForeignKey(
        Document,
        on_delete=models.PROTECT,
        related_name="credits_given",
    )
    destination_invoice = models.ForeignKey(
        Document,
        on_delete=models.PROTECT,
        related_name="credits_received",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~Q(source_invoice=F("destination_invoice")),
                name="documents_credit_distinct_invoices",
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="documents_credit_amount_positive",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.source_invoice_id and self.destination_invoice_id:
            source = self.source_invoice
            destination = self.destination_invoice
            if source.company_id != destination.company_id:
                errors["destination_invoice"] = "Invoices must share a company."
            if source.project_id != destination.project_id:
                errors["destination_invoice"] = "Invoices must share a project."
            if source.invoice_kind != Document.InvoiceKind.RETAINER:
                errors["source_invoice"] = "Credit source must be a retainer invoice."
            if destination.invoice_kind != Document.InvoiceKind.FINAL:
                errors["destination_invoice"] = "Credit destination must be final."
        if errors:
            raise ValidationError(errors)


class DocumentNumberSequence(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="document_number_sequences",
    )
    doc_type = models.CharField(max_length=20, choices=Document.Type.choices)
    period = models.CharField(max_length=2)
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("company", "doc_type", "period"),
                name="documents_company_type_period_sequence_unique",
            )
        ]

    def __str__(self):
        return f"{self.company}: {self.doc_type}/{self.period}/{self.last_value}"

