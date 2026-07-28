# Generated manually for the EZ360PM AI assistant foundation.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "0002_company_default_invoice_due_days_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AIInteraction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(max_length=50)),
                ("model", models.CharField(max_length=100)),
                ("prompt_summary", models.CharField(max_length=500)),
                ("response_summary", models.CharField(blank=True, max_length=1000)),
                ("status", models.CharField(choices=[("started", "Started"), ("completed", "Completed"), ("failed", "Failed"), ("blocked", "Blocked")], default="started", max_length=20)),
                ("input_tokens", models.PositiveIntegerField(default=0)),
                ("output_tokens", models.PositiveIntegerField(default=0)),
                ("total_tokens", models.PositiveIntegerField(default=0)),
                ("estimated_cost_usd", models.DecimalField(decimal_places=6, default=0, max_digits=12)),
                ("latency_ms", models.PositiveIntegerField(default=0)),
                ("error_code", models.CharField(blank=True, max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ai_interactions", to="accounts.company")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ai_interactions", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("-created_at", "-pk"),
                "indexes": [models.Index(fields=["company", "created_at"], name="ai_inter_company_created"), models.Index(fields=["user", "created_at"], name="ai_inter_user_created")],
            },
        ),
        migrations.CreateModel(
            name="AIActionAttempt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tool_name", models.CharField(max_length=100)),
                ("risk_level", models.CharField(choices=[("low_write", "Low-risk write"), ("structured_write", "Structured write"), ("financial_draft", "Financial draft"), ("external_commit", "External or financial commit")], max_length=30)),
                ("normalized_arguments", models.JSONField(default=dict)),
                ("preview", models.JSONField(default=dict)),
                ("status", models.CharField(choices=[("pending", "Pending confirmation"), ("confirmed", "Confirmed"), ("completed", "Completed"), ("canceled", "Canceled"), ("expired", "Expired"), ("failed", "Failed")], default="pending", max_length=20)),
                ("confirmation_token", models.UUIDField(default=uuid.uuid4, unique=True)),
                ("confirmation_expires_at", models.DateTimeField()),
                ("idempotency_key", models.CharField(max_length=64, unique=True)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("executed_at", models.DateTimeField(blank=True, null=True)),
                ("result", models.JSONField(blank=True, default=dict)),
                ("error_code", models.CharField(blank=True, max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ai_action_attempts", to="accounts.company")),
                ("interaction", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="action_attempts", to="assistant.aiinteraction")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ai_action_attempts", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("-created_at", "-pk"),
                "indexes": [models.Index(fields=["company", "status", "created_at"], name="ai_action_company_status"), models.Index(fields=["user", "status", "created_at"], name="ai_action_user_status")],
            },
        ),
    ]
