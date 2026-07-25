from decimal import Decimal

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0007_paymentadjustment"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentFeeReconciliationAttempt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("resolved", "Resolved"),
                            ("pending", "Still pending"),
                            ("error", "Provider error"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "observed_fee",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=12,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0"))
                        ],
                    ),
                ),
                ("error_code", models.CharField(blank=True, max_length=100)),
                ("error_message", models.CharField(blank=True, max_length=255)),
                ("attempted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="accounts.company",
                    ),
                ),
                (
                    "payment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="fee_reconciliation_attempts",
                        to="documents.payment",
                    ),
                ),
            ],
            options={
                "ordering": ("-attempted_at", "-pk"),
                "indexes": [
                    models.Index(
                        fields=["company", "status", "attempted_at"],
                        name="doc_fee_company_status_idx",
                    ),
                    models.Index(
                        fields=["payment", "attempted_at"],
                        name="doc_fee_payment_attempt_idx",
                    ),
                ],
            },
        ),
    ]
