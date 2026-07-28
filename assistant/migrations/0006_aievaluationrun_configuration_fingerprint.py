from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0005_aievaluationrun_aievaluationcaseresult"),
    ]

    operations = [
        migrations.AddField(
            model_name="aievaluationrun",
            name="configuration_fingerprint",
            field=models.CharField(blank=True, max_length=64),
        ),
    ]
