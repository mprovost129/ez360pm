from decimal import Decimal

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def copy_current_fees(apps, schema_editor):
    Payment = apps.get_model("documents", "Payment")
    for payment in Payment.objects.all().iterator():
        payment.fee_current_amount = payment.fee_amount
        payment.save(update_fields=["fee_current_amount"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_company_default_invoice_due_days_and_more"),
        ("documents", "0006_alter_documentdelivery_purpose"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="fee_current_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Most recent provider fee used to calculate later fee adjustments.",
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))],
            ),
        ),
        migrations.RunPython(copy_current_fees, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.CheckConstraint(
                condition=models.Q(("fee_current_amount__gte", 0)),
                name="documents_payment_current_fee_nonnegative",
            ),
        ),
        migrations.CreateModel(
            name="PaymentAdjustment",
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
                    "adjustment_type",
                    models.CharField(
                        choices=[
                            ("refund", "Refund"),
                            ("fee_refund", "Processing fee refund"),
                            ("fee_adjustment", "Additional processing fee"),
                            ("dispute", "Dispute / chargeback"),
                            ("dispute_reversal", "Dispute reversal"),
                            ("correction", "Correction"),
                            ("other", "Other adjustment"),
                        ],
                        max_length=30,
                    ),
                ),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("effective_at", models.DateField(default=django.utils.timezone.localdate)),
                (
                    "affects_invoice_balance",
                    models.BooleanField(
                        default=True,
                        help_text="Include this adjustment when calculating the invoice balance.",
                    ),
                ),
                (
                    "affects_processing_fees",
                    models.BooleanField(
                        default=False,
                        help_text=(
                            "Treat this signed adjustment as a change to provider "
                            "processing fees instead of a customer refund or revenue "
                            "correction."
                        ),
                    ),
                ),
                (
                    "provider_id",
                    models.CharField(
                        blank=True,
                        help_text="Stripe refund/dispute identifier used for idempotency.",
                        max_length=255,
                    ),
                ),
                ("reference", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
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
                        related_name="adjustments",
                        to="documents.payment",
                    ),
                ),
            ],
            options={
                "ordering": ("-effective_at", "-created_at", "-pk"),
                "indexes": [
                    models.Index(
                        fields=["company", "effective_at"],
                        name="documents_p_company_6ae534_idx",
                    ),
                    models.Index(
                        fields=["payment", "effective_at"],
                        name="documents_p_payment_797d69_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("amount", 0), _negated=True),
                        name="documents_adjustment_amount_nonzero",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("provider_id", ""), _negated=True),
                        fields=("company", "provider_id"),
                        name="documents_adjustment_provider_company_unique",
                    ),
                ],
            },
        ),
    ]
