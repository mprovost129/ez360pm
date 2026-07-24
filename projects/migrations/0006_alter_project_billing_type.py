from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0005_timeentry_paused_at_timeentry_paused_duration_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="project",
            name="billing_type",
            field=models.CharField(
                choices=[("hourly", "Hourly"), ("flat_fee", "Fixed fee")],
                max_length=20,
            ),
        ),
    ]
