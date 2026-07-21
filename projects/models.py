from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

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
    postal_code = models.CharField(max_length=20)
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
