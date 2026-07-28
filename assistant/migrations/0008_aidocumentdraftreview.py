# Generated for EZ360PM V1.12.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0007_ai_pilot_operations"),
        ("documents", "0007_documentdelivery_subject_message"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AIDocumentDraftReview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("document_type", models.CharField(max_length=20)),
                ("document_number", models.CharField(max_length=30)),
                ("initial_snapshot", models.JSONField(default=dict)),
                ("latest_snapshot", models.JSONField(default=dict)),
                ("initial_snapshot_hash", models.CharField(max_length=64)),
                ("latest_snapshot_hash", models.CharField(max_length=64)),
                ("changed_fields", models.JSONField(blank=True, default=list)),
                ("revision_count", models.PositiveIntegerField(default=0)),
                ("outcome", models.CharField(choices=[("active", "Still a draft"), ("used_as_is", "Issued without revision"), ("edited_then_used", "Revised before issue"), ("abandoned", "Deleted while draft")], default="active", max_length=30)),
                ("first_revised_at", models.DateTimeField(blank=True, null=True)),
                ("last_revised_at", models.DateTimeField(blank=True, null=True)),
                ("issued_at", models.DateTimeField(blank=True, null=True)),
                ("first_delivery_at", models.DateTimeField(blank=True, null=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("action_attempt", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="document_draft_review", to="assistant.aiactionattempt")),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ai_document_draft_reviews", to="accounts.company")),
                ("document", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ai_draft_reviews", to="documents.document")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ai_document_draft_reviews", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("-created_at", "-pk"),
            },
        ),
        migrations.AddIndex(
            model_name="aidocumentdraftreview",
            index=models.Index(fields=["company", "outcome", "created_at"], name="ai_draft_company_outcome"),
        ),
        migrations.AddIndex(
            model_name="aidocumentdraftreview",
            index=models.Index(fields=["company", "document_type", "created_at"], name="ai_draft_company_type"),
        ),
    ]
