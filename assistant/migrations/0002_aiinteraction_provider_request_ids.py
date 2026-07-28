from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="aiinteraction",
            name="provider_request_ids",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
