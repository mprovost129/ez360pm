from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0009_ai_conversation_and_page_context"),
    ]

    operations = [
        migrations.AddField(
            model_name="aiinteraction",
            name="provider_client_request_ids",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
