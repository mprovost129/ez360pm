from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


def create_existing_company_settings(apps, schema_editor):
    del schema_editor
    Company = apps.get_model("accounts", "Company")
    AICompanySettings = apps.get_model("assistant", "AICompanySettings")
    now = timezone.now()
    for company in Company.objects.all().iterator():
        AICompanySettings.objects.get_or_create(
            company=company,
            defaults={
                "enabled": True,
                "allow_low_risk_writes": True,
                "allow_structured_writes": True,
                "allow_financial_drafts": True,
                "allow_external_commits": True,
                "proactive_insights_enabled": True,
                "monthly_cost_limit_usd": Decimal("25.00"),
                "monthly_request_limit": 500,
                "interaction_retention_days": 90,
                "retain_interaction_summaries": True,
                "privacy_notice_version": "2026-07-27",
                "privacy_notice_acknowledged_at": now,
            },
        )


def remove_company_settings(apps, schema_editor):
    del schema_editor
    AICompanySettings = apps.get_model("assistant", "AICompanySettings")
    AICompanySettings.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_company_default_invoice_due_days_and_more"),
        ("assistant", "0003_aievent_aiinsightdismissal"),
    ]

    operations = [
        migrations.CreateModel(
            name="AICompanySettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=False)),
                ("model_override", models.CharField(blank=True, max_length=100)),
                ("allow_low_risk_writes", models.BooleanField(default=True)),
                ("allow_structured_writes", models.BooleanField(default=True)),
                ("allow_financial_drafts", models.BooleanField(default=True)),
                ("allow_external_commits", models.BooleanField(default=False)),
                ("proactive_insights_enabled", models.BooleanField(default=True)),
                (
                    "monthly_cost_limit_usd",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("25.00"),
                        max_digits=10,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0.01")),
                            django.core.validators.MaxValueValidator(Decimal("100000.00")),
                        ],
                    ),
                ),
                (
                    "monthly_request_limit",
                    models.PositiveIntegerField(
                        default=500,
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(1000000),
                        ],
                    ),
                ),
                (
                    "interaction_retention_days",
                    models.PositiveSmallIntegerField(
                        default=90,
                        validators=[
                            django.core.validators.MinValueValidator(7),
                            django.core.validators.MaxValueValidator(2555),
                        ],
                    ),
                ),
                ("retain_interaction_summaries", models.BooleanField(default=True)),
                ("privacy_notice_version", models.CharField(blank=True, max_length=40)),
                ("privacy_notice_acknowledged_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "company",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_settings",
                        to="accounts.company",
                    ),
                ),
            ],
            options={
                "verbose_name": "AI company setting",
                "verbose_name_plural": "AI company settings",
            },
        ),
        migrations.RunPython(create_existing_company_settings, remove_company_settings),
    ]
