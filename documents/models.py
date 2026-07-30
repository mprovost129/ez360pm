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
        RETAINER = "retainer", "Deposit / retainer"
        FINAL = "final", "Final"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        VIEWED = "viewed", "Link opened"
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
    source_invoice = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="follow_up_invoices",
        blank=True,
        null=True,
        help_text="Deposit invoice from which this final invoice was generated.",
    )
    number = models.CharField(max_length=50, blank=True)
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
    deposit_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Current amount due on a deposit invoice while total retains the full project value.",
    )
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
            models.CheckConstraint(
                condition=(
                    Q(deposit_amount__isnull=True)
                    | Q(
                        doc_type="invoice",
                        invoice_kind="retainer",
                        deposit_amount__gt=0,
                    )
                ),
                name="documents_deposit_matches_retainer",
            ),
        ]
        indexes = [
            models.Index(fields=("company", "doc_type", "status")),
            models.Index(fields=("company", "project", "doc_type")),
            models.Index(fields=("company", "due_date")),
        ]

    @classmethod
    def allowed_statuses_for_type(cls, doc_type):
        if doc_type == cls.Type.INVOICE:
            return (
                cls.Status.DRAFT,
                cls.Status.SENT,
                cls.Status.VIEWED,
                cls.Status.PARTIALLY_PAID,
                cls.Status.PAID,
                cls.Status.VOID,
            )
        if doc_type == cls.Type.PROPOSAL:
            return (
                cls.Status.DRAFT,
                cls.Status.SENT,
                cls.Status.VIEWED,
                cls.Status.ACCEPTED,
                cls.Status.DECLINED,
                cls.Status.WITHDRAWN,
            )
        return ()

    @classmethod
    def status_choices_for_type(cls, doc_type):
        return [
            (status.value, status.label)
            for status in cls.allowed_statuses_for_type(doc_type)
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
        else:
            if self.invoice_kind:
                errors["invoice_kind"] = "Proposals cannot have an invoice kind."
            if self.due_date is not None:
                errors["due_date"] = "Proposals cannot have a due date."
        allowed = self.allowed_statuses_for_type(self.doc_type)
        if self.status not in allowed:
            errors["status"] = "Status is not valid for this document type."
        if self.source_proposal_id:
            if self.source_proposal.doc_type != self.Type.PROPOSAL:
                errors["source_proposal"] = "Source document must be a proposal."
            elif self.source_proposal.project_id != self.project_id:
                errors["source_proposal"] = "Source proposal must use the same project."
        if self.source_invoice_id:
            source = self.source_invoice
            if self.doc_type != self.Type.INVOICE or self.invoice_kind != self.InvoiceKind.FINAL:
                errors["source_invoice"] = "Only final invoices can reference a deposit invoice."
            elif source.doc_type != self.Type.INVOICE or source.invoice_kind != self.InvoiceKind.RETAINER:
                errors["source_invoice"] = "Source invoice must be a deposit / retainer invoice."
            elif source.company_id != self.company_id or source.project_id != self.project_id:
                errors["source_invoice"] = "Source invoice must use the same company and project."
        if self.deposit_amount is not None:
            if self.doc_type != self.Type.INVOICE or self.invoice_kind != self.InvoiceKind.RETAINER:
                errors["deposit_amount"] = "A deposit amount requires a deposit / retainer invoice."
            elif self.deposit_amount <= 0:
                errors["deposit_amount"] = "Deposit amount must be positive."
            elif self.total > 0 and self.deposit_amount > self.total:
                errors["deposit_amount"] = "Deposit amount cannot exceed the invoice total."
        if errors:
            raise ValidationError(errors)

    @property
    def amount_paid(self):
        return self.payments.aggregate(value=Sum("amount"))["value"] or Decimal("0.00")

    @property
    def gross_total(self):
        return self.subtotal + self.tax_total

    @property
    def amount_due(self):
        if self.invoice_kind == self.InvoiceKind.RETAINER and self.deposit_amount is not None:
            return self.deposit_amount
        return self.total

    @property
    def outstanding_balance(self):
        return max(self.amount_due - self.amount_paid, Decimal("0.00"))

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

    def delete(self, *args, **kwargs):
        if self.status != self.Status.DRAFT:
            raise ValidationError("Issued documents must be voided or withdrawn, not deleted.")
        return super().delete(*args, **kwargs)


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
    fee_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Processing fee withheld by the provider (0 for manual payments).",
    )
    fee_pending = models.BooleanField(
        default=False,
        help_text="Stripe has not yet supplied the final processing fee.",
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
            ),
            models.CheckConstraint(
                condition=Q(fee_amount__gte=0),
                name="documents_payment_fee_nonnegative",
            ),
        ]
        indexes = [models.Index(fields=("document", "received_at"))]

    def clean(self):
        super().clean()
        if self.document_id and self.document.doc_type != Document.Type.INVOICE:
            raise ValidationError({"document": "Payments require an invoice."})

    def __str__(self):
        return f"{self.get_method_display()} payment of {self.amount}"

    @property
    def net_amount(self):
        return self.amount - self.fee_amount


class DocumentDelivery(models.Model):
    """Durable attempt history for every transactional application email.

    The historical name is retained for migration and API compatibility. New
    deliveries may target either a financial document or a project client form.
    """

    class Purpose(models.TextChoices):
        CLIENT_DOCUMENT = "client_document", "Client document"
        CLIENT_FOLLOW_UP = "client_follow_up", "Client follow-up"
        ACCEPTANCE_NOTIFICATION = "acceptance_notification", "Acceptance notification"
        DECLINE_NOTIFICATION = "decline_notification", "Decline notification"
        PAYMENT_NOTIFICATION = "payment_notification", "Payment notification"
        CLIENT_FORM = "client_form", "Client form"
        CLIENT_FORM_SUBMISSION = "client_form_submission", "Form submission notification"

    class FollowUpKind(models.TextChoices):
        PROPOSAL = "proposal", "Proposal follow-up"
        RETAINER = "retainer", "Retainer reminder"
        INVOICE = "invoice", "Invoice reminder"
        OVERDUE_INVOICE = "overdue_invoice", "Overdue invoice reminder"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        DELIVERED = "delivered", "Delivered"
        DELAYED = "delayed", "Delivery delayed"
        BOUNCED = "bounced", "Bounced"
        COMPLAINED = "complained", "Marked as spam"
        SUPPRESSED = "suppressed", "Suppressed"
        FAILED = "failed", "Failed"

    class Provider(models.TextChoices):
        DJANGO = "django", "Django email backend"
        RESEND = "resend", "Resend"

    document = models.ForeignKey(
        Document,
        on_delete=models.PROTECT,
        related_name="deliveries",
        blank=True,
        null=True,
    )
    project_form = models.ForeignKey(
        "projects.ProjectClientForm",
        on_delete=models.PROTECT,
        related_name="email_deliveries",
        blank=True,
        null=True,
    )
    purpose = models.CharField(
        max_length=30,
        choices=Purpose.choices,
        default=Purpose.CLIENT_DOCUMENT,
    )
    follow_up_kind = models.CharField(
        max_length=30,
        choices=FollowUpKind.choices,
        blank=True,
    )
    recipient_name = models.CharField(max_length=255)
    recipient_email = models.EmailField()
    subject = models.CharField(max_length=255, blank=True)
    message = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    provider_message_id = models.CharField(max_length=255, blank=True)
    provider = models.CharField(max_length=20, choices=Provider.choices, blank=True)
    dedupe_key = models.CharField(max_length=255, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    last_event_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=("document", "status")),
            models.Index(fields=("project_form", "status")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("dedupe_key",),
                condition=~Q(dedupe_key=""),
                name="documents_delivery_dedupe_key_unique",
            ),
            models.UniqueConstraint(
                fields=("provider", "provider_message_id"),
                condition=~Q(provider_message_id=""),
                name="documents_delivery_provider_message_unique",
            ),
            models.CheckConstraint(
                condition=(
                    Q(document__isnull=False, project_form__isnull=True)
                    | Q(document__isnull=True, project_form__isnull=False)
                ),
                name="documents_delivery_has_one_target",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        project_form__isnull=False,
                        purpose__in=("client_form", "client_form_submission"),
                    )
                    | Q(
                        document__isnull=False,
                        purpose__in=(
                            "client_document",
                            "client_follow_up",
                            "acceptance_notification",
                            "decline_notification",
                            "payment_notification",
                        ),
                    )
                ),
                name="documents_delivery_purpose_matches_target",
            ),
        ]

    def __str__(self):
        target = self.document.number if self.document_id else self.project_form.title
        return f"{target} to {self.recipient_email}: {self.status}"

    @classmethod
    def successful_statuses(cls):
        return (cls.Status.SENT, cls.Status.DELIVERED, cls.Status.DELAYED)

    @classmethod
    def failed_statuses(cls):
        return (
            cls.Status.FAILED,
            cls.Status.BOUNCED,
            cls.Status.COMPLAINED,
            cls.Status.SUPPRESSED,
        )

    @property
    def failure_message(self):
        """Turn provider error codes into useful next steps for the user."""

        if not self.error_code:
            return ""
        code = self.error_code.lower()
        if code == "email_not_configured":
            return "Email is not configured. Review the email settings and try again."
        if code in {"resend_api_key_missing", "email_provider_invalid"}:
            return "Resend is not fully configured. Review the email integration settings."
        if code.startswith("resend_http_401") or code.startswith("resend_http_403"):
            return "Resend rejected the API credentials or sending domain configuration."
        if code.startswith("resend_http_429"):
            return "Resend temporarily rate-limited this message. Wait and try again."
        if self.status == self.Status.BOUNCED:
            return "The recipient's mail server permanently rejected this email."
        if self.status == self.Status.COMPLAINED:
            return "The recipient marked this message as spam. Confirm the address before sending again."
        if self.status == self.Status.SUPPRESSED:
            return "Resend suppressed this address because of prior delivery problems."
        if "authentication" in code:
            return "The email provider rejected the login. Check the SMTP username and password."
        if any(token in code for token in ("timeout", "connection", "socket")):
            return "The email provider could not be reached. Check the SMTP host and try again."
        if code == "provider_did_not_confirm_send":
            return "The email provider did not confirm the send. Try again before sending it manually."
        if code == "interrupted_before_provider_confirmation":
            return "The send was interrupted before delivery was confirmed. Try again."
        return "The email provider rejected the message. Review the email settings and try again."


class EmailWebhookEvent(models.Model):
    """One verified provider event, retained for replay and ordering safety."""

    delivery = models.ForeignKey(
        DocumentDelivery,
        on_delete=models.CASCADE,
        related_name="provider_events",
        blank=True,
        null=True,
    )
    provider = models.CharField(
        max_length=20,
        choices=DocumentDelivery.Provider.choices,
        default=DocumentDelivery.Provider.RESEND,
    )
    event_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=50)
    provider_message_id = models.CharField(max_length=255, blank=True)
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-occurred_at", "-pk")
        indexes = [models.Index(fields=("provider", "provider_message_id"))]
        constraints = [
            models.UniqueConstraint(
                fields=("provider", "event_id"),
                name="documents_email_event_provider_id_unique",
            )
        ]

    def __str__(self):
        return f"{self.event_type}: {self.provider_message_id or self.event_id}"


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
