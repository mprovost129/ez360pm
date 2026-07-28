from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("documents", "0006_alter_documentdelivery_purpose")]

    operations = [
        migrations.AddField(
            model_name="documentdelivery",
            name="subject",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="documentdelivery",
            name="message",
            field=models.TextField(blank=True),
        ),
    ]
