import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0002_aiinteraction_provider_request_ids"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AIEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("ambiguity", "Ambiguity"), ("correction_requested", "Correction requested"), ("action_canceled", "Action canceled"), ("tool_failure", "Tool failure"), ("suggestion_used", "Suggestion used"), ("insight_dismissed", "Insight dismissed")], max_length=40)),
                ("capability", models.CharField(blank=True, max_length=100)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("action_attempt", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="events", to="assistant.aiactionattempt")),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ai_events", to="accounts.company")),
                ("interaction", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="events", to="assistant.aiinteraction")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ai_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at", "-pk")},
        ),
        migrations.CreateModel(
            name="AIInsightDismissal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("insight_key", models.CharField(max_length=255)),
                ("dismissed_until", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ai_insight_dismissals", to="accounts.company")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ai_insight_dismissals", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(model_name="aievent", index=models.Index(fields=["company", "event_type", "created_at"], name="ai_event_company_type")),
        migrations.AddIndex(model_name="aievent", index=models.Index(fields=["user", "created_at"], name="ai_event_user_created")),
        migrations.AddIndex(model_name="aiinsightdismissal", index=models.Index(fields=["company", "user", "dismissed_until"], name="ai_insight_dismissed_until")),
        migrations.AddConstraint(model_name="aiinsightdismissal", constraint=models.UniqueConstraint(fields=("company", "user", "insight_key"), name="ai_insight_dismissal_unique")),
    ]
