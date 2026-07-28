from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0008_aidocumentdraftreview"),
    ]

    operations = [
        migrations.AddField(
            model_name="aiinteraction",
            name="conversation_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="aiinteraction",
            name="context_turn_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="aiinteraction",
            name="page_context_object_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="aiinteraction",
            name="page_context_type",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddIndex(
            model_name="aiinteraction",
            index=models.Index(
                fields=["company", "user", "conversation_id", "created_at"],
                name="ai_inter_conversation",
            ),
        ),
    ]
