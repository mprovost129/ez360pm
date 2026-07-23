from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from accounts.models import Company, CompanyOwnedModel
from clients.models import Client


class Project(CompanyOwnedModel):
    class Status(models.TextChoices):
        LEAD = "lead", "Lead"
        APPROVED = "approved", "Approved"
        ACTIVE = "active", "Active"
        ON_HOLD = "on_hold", "On hold"
        COMPLETED = "completed", "Completed"
        CANCELED = "canceled", "Canceled"

    class BillingType(models.TextChoices):
        HOURLY = "hourly", "Hourly"
        FLAT_FEE = "flat_fee", "Flat fee"

    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        related_name="projects",
    )
    number = models.CharField(max_length=30, blank=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    address_1 = models.CharField(max_length=255)
    address_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20, blank=True)
    municipality = models.CharField(max_length=100, blank=True)
    parcel_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.LEAD,
    )
    billing_type = models.CharField(max_length=20, choices=BillingType.choices)
    hourly_rate = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    fixed_fee = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    estimated_hours = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-number", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("company", "number"),
                name="projects_company_number_unique",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        billing_type="hourly",
                        hourly_rate__isnull=False,
                        fixed_fee__isnull=True,
                    )
                    | models.Q(
                        billing_type="flat_fee",
                        fixed_fee__isnull=False,
                        hourly_rate__isnull=True,
                    )
                ),
                name="projects_billing_fields_match_type",
            ),
        ]
        indexes = [
            models.Index(fields=("company", "status")),
            models.Index(fields=("company", "number")),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.client_id and self.company_id != self.client.company_id:
            errors["client"] = "Client must belong to the same company."
        if self.billing_type == self.BillingType.HOURLY:
            if self.hourly_rate is None:
                errors["hourly_rate"] = "Hourly projects require an hourly rate."
            if self.fixed_fee is not None:
                errors["fixed_fee"] = "Hourly projects cannot have a fixed fee."
        elif self.billing_type == self.BillingType.FLAT_FEE:
            if self.fixed_fee is None:
                errors["fixed_fee"] = "Flat-fee projects require a fixed fee."
            if self.hourly_rate is not None:
                errors["hourly_rate"] = "Flat-fee projects cannot have an hourly rate."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.number} - {self.name}"

    @property
    def actual_duration(self):
        durations = (
            self.time_entries.filter(end_time__isnull=False)
            .values_list("start_time", "end_time", "paused_duration")
            .iterator()
        )
        return sum(
            (max(end - start - paused, timedelta()) for start, end, paused in durations),
            timedelta(),
        )

    @property
    def actual_hours(self):
        microseconds = self.actual_duration // timedelta(microseconds=1)
        hours = Decimal(microseconds) / Decimal("3600000000")
        return hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def effective_hourly_rate(self):
        hours = self.actual_hours
        if not hours:
            return None
        if self.billing_type == self.BillingType.FLAT_FEE:
            earned = self.fixed_fee
        else:
            from documents.models import Document

            earned = self.documents.filter(
                doc_type=Document.Type.INVOICE,
                invoice_kind=Document.InvoiceKind.FINAL,
                status__in=(
                    Document.Status.SENT,
                    Document.Status.VIEWED,
                    Document.Status.PARTIALLY_PAID,
                    Document.Status.PAID,
                ),
            ).aggregate(value=models.Sum("subtotal"))["value"]
        if not earned:
            return None
        return (earned / hours).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    @property
    def accepts_time(self):
        return self.status in {
            self.Status.LEAD,
            self.Status.APPROVED,
            self.Status.ACTIVE,
        }


class ProjectNumberSequence(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="project_number_sequences",
    )
    period = models.CharField(max_length=4)
    last_value = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("company", "period"),
                name="projects_company_period_sequence_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(last_value__lte=999),
                name="projects_sequence_at_most_999",
            ),
        ]

    def __str__(self):
        return f"{self.company}: {self.period}/{self.last_value}"


class TimeEntry(CompanyOwnedModel):
    class Status(models.TextChoices):
        LOGGED = "logged", "Logged"
        INVOICED = "invoiced", "Invoiced"

    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="time_entries",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="time_entries",
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(blank=True, null=True)
    paused_at = models.DateTimeField(blank=True, null=True)
    paused_duration = models.DurationField(default=timedelta)
    description = models.CharField(max_length=255, blank=True)
    billable = models.BooleanField(default=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.LOGGED,
    )
    line_item = models.ForeignKey(
        "documents.LineItem",
        on_delete=models.SET_NULL,
        related_name="time_entries",
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ("-start_time", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("user",),
                condition=Q(end_time__isnull=True),
                name="projects_one_running_timer_per_user",
            ),
            models.CheckConstraint(
                condition=Q(end_time__isnull=True) | Q(end_time__gt=F("start_time")),
                name="projects_time_end_after_start",
            ),
            models.CheckConstraint(
                condition=Q(end_time__isnull=False) | Q(status="logged"),
                name="projects_running_time_is_logged",
            ),
            models.CheckConstraint(
                condition=Q(end_time__isnull=True) | Q(paused_at__isnull=True),
                name="projects_time_no_pause_after_stop",
            ),
        ]
        indexes = [
            models.Index(fields=("company", "project", "start_time")),
            models.Index(fields=("company", "status", "billable")),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.project_id and self.project.company_id != self.company_id:
            errors["project"] = "Project must belong to the same company."
        if self.user_id and self.user.company_id != self.company_id:
            errors["user"] = "User must belong to the same company."
        if self.end_time and self.start_time and self.end_time <= self.start_time:
            errors["end_time"] = "End time must be after start time."
        if self.end_time is None and self.status != self.Status.LOGGED:
            errors["status"] = "A running timer must be logged, not invoiced."
        if self.paused_at is not None and self.end_time is not None:
            errors["paused_at"] = "A stopped time entry cannot be paused."
        if errors:
            raise ValidationError(errors)

    @property
    def is_paused(self):
        return self.paused_at is not None

    @property
    def is_running(self):
        return self.end_time is None

    @property
    def duration(self):
        effective_end = self.end_time or self.paused_at or timezone.now()
        return max(effective_end - self.start_time - self.paused_duration, timedelta())

    @property
    def duration_hours(self):
        microseconds = self.duration // timedelta(microseconds=1)
        hours = Decimal(microseconds) / Decimal("3600000000")
        return hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def __str__(self):
        return f"{self.project.number}: {self.description or 'Time entry'}"
