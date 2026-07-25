from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_company_default_invoice_due_days_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="books_closed_through",
            field=models.DateField(
                blank=True,
                help_text=(
                    "Payments and manual adjustments dated on or before this date "
                    "cannot be edited or deleted through the application."
                ),
                null=True,
            ),
        ),
    ]
