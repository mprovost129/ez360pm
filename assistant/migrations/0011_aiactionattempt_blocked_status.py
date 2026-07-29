from django.db import migrations, models


def reclassify_domain_validation_actions(apps, schema_editor):
    del schema_editor
    AIActionAttempt = apps.get_model("assistant", "AIActionAttempt")
    AIEvent = apps.get_model("assistant", "AIEvent")
    legacy_attempts = AIActionAttempt.objects.filter(
        status="failed",
        error_code="domain_validation",
    )
    AIEvent.objects.filter(
        action_attempt__in=legacy_attempts,
        event_type="tool_failure",
    ).update(event_type="correction_requested")
    legacy_attempts.update(status="blocked")


def restore_legacy_status(apps, schema_editor):
    del schema_editor
    AIActionAttempt = apps.get_model("assistant", "AIActionAttempt")
    AIEvent = apps.get_model("assistant", "AIEvent")
    blocked_attempts = AIActionAttempt.objects.filter(
        status="blocked",
        error_code="domain_validation",
    )
    AIEvent.objects.filter(
        action_attempt__in=blocked_attempts,
        event_type="correction_requested",
    ).update(event_type="tool_failure")
    blocked_attempts.update(status="failed")


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0010_aiinteraction_provider_client_request_ids"),
    ]

    operations = [
        migrations.RunPython(
            reclassify_domain_validation_actions,
            restore_legacy_status,
        ),
        migrations.AlterField(
            model_name="aiactionattempt",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending confirmation"),
                    ("confirmed", "Confirmed"),
                    ("completed", "Completed"),
                    ("canceled", "Canceled"),
                    ("expired", "Expired"),
                    ("blocked", "Needs correction"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
