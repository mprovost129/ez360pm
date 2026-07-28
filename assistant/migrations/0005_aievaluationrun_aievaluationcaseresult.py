import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_company_default_invoice_due_days_and_more"),
        ("assistant", "0004_aicompanysettings"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AIEvaluationRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mode", models.CharField(choices=[("contract", "Contract"), ("live", "Live OpenAI")], max_length=20)),
                ("suite", models.CharField(max_length=40)),
                ("model", models.CharField(blank=True, max_length=100)),
                ("status", models.CharField(choices=[("running", "Running"), ("passed", "Passed"), ("failed", "Failed"), ("error", "Error")], default="running", max_length=20)),
                ("total_cases", models.PositiveIntegerField(default=0)),
                ("passed_cases", models.PositiveIntegerField(default=0)),
                ("failed_cases", models.PositiveIntegerField(default=0)),
                ("total_tokens", models.PositiveIntegerField(default=0)),
                ("estimated_cost_usd", models.DecimalField(decimal_places=6, default=0, max_digits=12)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("company", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="ai_evaluation_runs", to="accounts.company")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ai_evaluation_runs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-started_at", "-pk")},
        ),
        migrations.CreateModel(
            name="AIEvaluationCaseResult",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("case_id", models.CharField(max_length=100)),
                ("title", models.CharField(max_length=255)),
                ("category", models.CharField(max_length=50)),
                ("status", models.CharField(choices=[("passed", "Passed"), ("failed", "Failed"), ("error", "Error"), ("skipped", "Skipped")], max_length=20)),
                ("expected_tools", models.JSONField(blank=True, default=list)),
                ("forbidden_risk_levels", models.JSONField(blank=True, default=list)),
                ("actual_tools", models.JSONField(blank=True, default=list)),
                ("pending_action_count", models.PositiveIntegerField(default=0)),
                ("response_summary", models.CharField(blank=True, max_length=1000)),
                ("error_code", models.CharField(blank=True, max_length=100)),
                ("total_tokens", models.PositiveIntegerField(default=0)),
                ("estimated_cost_usd", models.DecimalField(decimal_places=6, default=0, max_digits=12)),
                ("latency_ms", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="case_results", to="assistant.aievaluationrun")),
            ],
            options={"ordering": ("run", "case_id")},
        ),
        migrations.AddIndex(
            model_name="aievaluationrun",
            index=models.Index(fields=["company", "started_at"], name="ai_eval_company_started"),
        ),
        migrations.AddConstraint(
            model_name="aievaluationcaseresult",
            constraint=models.UniqueConstraint(fields=("run", "case_id"), name="ai_eval_case_unique"),
        ),
    ]
