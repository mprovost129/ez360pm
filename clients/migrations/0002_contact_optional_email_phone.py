from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("clients", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="contact",
            name="email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AlterField(
            model_name="contact",
            name="phone",
            field=models.CharField(blank=True, max_length=50),
        ),
    ]
