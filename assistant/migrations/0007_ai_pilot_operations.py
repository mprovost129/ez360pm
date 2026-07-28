import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def create_user_access(apps, schema_editor):
    del schema_editor
    User = apps.get_model("accounts", "User")
    AIUserAccess = apps.get_model("assistant", "AIUserAccess")
    for user in User.objects.all().iterator():
        AIUserAccess.objects.get_or_create(
            user=user,
            defaults={
                "company_id": user.company_id,
                "enabled": True,
                "granted_by_id": user.pk if user.is_staff else None,
            },
        )


def remove_user_access(apps, schema_editor):
    del schema_editor
    apps.get_model("assistant", "AIUserAccess").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("assistant", "0006_aievaluationrun_configuration_fingerprint"),
    ]

    operations = [
        migrations.AddField(
            model_name="aicompanysettings",
            name="access_mode",
            field=models.CharField(
                choices=[
                    ("staff_only", "Staff users only"),
                    ("selected_users", "Selected users"),
                    ("all_users", "All company users"),
                ],
                default="all_users",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="aicompanysettings",
            name="auto_pause_on_failures",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="aicompanysettings",
            name="failure_threshold",
            field=models.PositiveSmallIntegerField(
                default=5,
                validators=[
                    django.core.validators.MinValueValidator(2),
                    django.core.validators.MaxValueValidator(100),
                ],
            ),
        ),
        migrations.AddField(
            model_name="aicompanysettings",
            name="failure_window_minutes",
            field=models.PositiveSmallIntegerField(
                default=60,
                validators=[
                    django.core.validators.MinValueValidator(5),
                    django.core.validators.MaxValueValidator(1440),
                ],
            ),
        ),
        migrations.AddField(
            model_name="aicompanysettings",
            name="suspended_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="aicompanysettings",
            name="suspension_reason",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="aicompanysettings",
            name="failure_count_reset_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="aievent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("ambiguity", "Ambiguity"),
                    ("correction_requested", "Correction requested"),
                    ("action_canceled", "Action canceled"),
                    ("tool_failure", "Tool failure"),
                    ("suggestion_used", "Suggestion used"),
                    ("insight_dismissed", "Insight dismissed"),
                    ("feedback_recorded", "Feedback recorded"),
                    ("circuit_breaker_tripped", "Circuit breaker tripped"),
                    ("circuit_breaker_reset", "Circuit breaker reset"),
                ],
                max_length=40,
            ),
        ),
        migrations.CreateModel(
            name="AIUserAccess",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=True)),
                ("granted_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_user_access_records",
                        to="accounts.company",
                    ),
                ),
                (
                    "granted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="granted_ai_access_records",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_access",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("user__email",)},
        ),
        migrations.AddConstraint(
            model_name="aiuseraccess",
            constraint=models.UniqueConstraint(
                fields=("company", "user"),
                name="ai_user_access_user_uniq",
            ),
        ),
        migrations.CreateModel(
            name="AIFeedback",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rating", models.CharField(choices=[("helpful", "Helpful"), ("not_helpful", "Not helpful")], max_length=20)),
                ("category", models.CharField(choices=[("answer", "Answer quality"), ("record_match", "Wrong or ambiguous record"), ("action", "Prepared or completed action"), ("speed", "Speed or availability"), ("other", "Other")], default="answer", max_length=30)),
                ("comment", models.CharField(blank=True, max_length=1000)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ai_feedback", to="accounts.company")),
                ("interaction", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="feedback", to="assistant.aiinteraction")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ai_feedback", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at", "-pk")},
        ),
        migrations.AddConstraint(
            model_name="aifeedback",
            constraint=models.UniqueConstraint(fields=("interaction", "user"), name="ai_feedback_user_uniq"),
        ),
        migrations.AddIndex(
            model_name="aifeedback",
            index=models.Index(fields=["company", "rating", "created_at"], name="ai_feedback_company_rating"),
        ),
        migrations.CreateModel(
            name="AIIncident",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("severity", models.CharField(choices=[("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")], max_length=20)),
                ("category", models.CharField(choices=[("wrong_answer", "Wrong answer"), ("wrong_record", "Wrong record"), ("duplicate_action", "Duplicate action"), ("unsafe_action", "Unsafe or unexpected action"), ("privacy", "Privacy concern"), ("provider", "OpenAI/provider failure"), ("other", "Other")], max_length=30)),
                ("summary", models.CharField(max_length=500)),
                ("details", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("open", "Open"), ("resolved", "Resolved"), ("dismissed", "Dismissed")], default="open", max_length=20)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("resolution_note", models.CharField(blank=True, max_length=1000)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("action_attempt", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="incidents", to="assistant.aiactionattempt")),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ai_incidents", to="accounts.company")),
                ("interaction", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="incidents", to="assistant.aiinteraction")),
                ("reported_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reported_ai_incidents", to=settings.AUTH_USER_MODEL)),
                ("resolved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="resolved_ai_incidents", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at", "-pk")},
        ),
        migrations.AddIndex(
            model_name="aiincident",
            index=models.Index(fields=["company", "status", "severity"], name="ai_incident_company_status"),
        ),
        migrations.RunPython(create_user_access, remove_user_access),
    ]
