from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0007_documentdelivery_subject_message"),
    ]

    operations = [
        migrations.AlterField(
            model_name="documentdelivery",
            name="purpose",
            field=models.CharField(
                choices=[
                    ("client_document", "Client document"),
                    ("client_follow_up", "Client follow-up"),
                    ("acceptance_notification", "Acceptance notification"),
                    ("decline_notification", "Decline notification"),
                    ("payment_notification", "Payment notification"),
                ],
                default="client_document",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="documentdelivery",
            name="follow_up_kind",
            field=models.CharField(
                blank=True,
                choices=[
                    ("proposal", "Proposal follow-up"),
                    ("retainer", "Retainer reminder"),
                    ("invoice", "Invoice reminder"),
                    ("overdue_invoice", "Overdue invoice reminder"),
                ],
                max_length=30,
            ),
        ),
    ]
