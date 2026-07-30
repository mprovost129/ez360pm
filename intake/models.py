import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from accounts.models import CompanyOwnedModel
from clients.models import Client
from projects.models import Project


class Note(CompanyOwnedModel):
    class ActivityType(models.TextChoices):
        GENERAL = "general", "General note"
        CLIENT_CHANGE = "client_change", "Client change"
        DECISION = "decision", "Decision"
        QUESTION = "question", "Question"
        ISSUE = "issue", "Issue"
        MEETING = "meeting", "Meeting note"
        SITE_OBSERVATION = "site_observation", "Site observation"

    class SourceType(models.TextChoices):
        INTERNAL = "internal", "Internal"
        EMAIL = "email", "Email"
        PHONE = "phone", "Phone call"
        MEETING = "meeting", "Meeting"
        CLIENT_FORM = "client_form", "Client form"
        DOCUMENT = "document", "Document"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACTION_REQUIRED = "action_required", "Action required"
        WAITING_CLIENT = "waiting_client", "Waiting on client"
        RESOLVED = "resolved", "Resolved"
        REFERENCE = "reference", "Reference only"

    title = models.CharField(max_length=255, blank=True)
    activity_type = models.CharField(
        max_length=30,
        choices=ActivityType.choices,
        default=ActivityType.GENERAL,
    )
    source_type = models.CharField(
        max_length=30,
        choices=SourceType.choices,
        default=SourceType.INTERNAL,
    )
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.OPEN,
    )
    contact_first_name = models.CharField(max_length=150, blank=True)
    contact_last_name = models.CharField(max_length=150, blank=True)
    prospect_company_name = models.CharField(max_length=255, blank=True)
    source_email = models.EmailField(blank=True)
    source_reference = models.CharField(
        max_length=500,
        blank=True,
        help_text="Email subject, message ID, document name, or another source reference.",
    )
    body = models.TextField()
    original_content = models.TextField(
        blank=True,
        help_text="Optional original email or source text retained for context.",
    )
    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        related_name="notes",
        blank=True,
        null=True,
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="notes",
        blank=True,
        null=True,
    )
    is_archived = models.BooleanField(default=False)
    follow_up_on = models.DateField(blank=True, null=True)
    resolved_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_notes",
        blank=True,
        null=True,
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="resolved_notes",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("is_archived", "-created_at", "-pk")
        indexes = [
            models.Index(fields=("company", "is_archived", "-created_at")),
            models.Index(fields=("company", "project", "status", "-created_at")),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.client_id and self.client.company_id != self.company_id:
            errors["client"] = "Client must belong to the same company."
        if self.project_id:
            if self.project.company_id != self.company_id:
                errors["project"] = "Project must belong to the same company."
            elif self.client_id and self.client_id != self.project.client_id:
                errors["client"] = "The selected client does not own this project."
            else:
                self.client = self.project.client
        if self.created_by_id and self.created_by.company_id != self.company_id:
            errors["created_by"] = "Creator must belong to the same company."
        if self.resolved_by_id and self.resolved_by.company_id != self.company_id:
            errors["resolved_by"] = "Resolver must belong to the same company."
        if errors:
            raise ValidationError(errors)

    def mark_status(self, status, *, user=None):
        self.status = status
        if status == self.Status.RESOLVED:
            self.resolved_at = self.resolved_at or timezone.now()
            self.resolved_by = user
        else:
            self.resolved_at = None
            self.resolved_by = None

    def __str__(self):
        return self.title or self.body[:80]


def note_attachment_path(instance, filename):
    suffix = Path(filename).suffix.lower()[:12]
    project_segment = (
        f"project_{instance.note.project_id}"
        if instance.note.project_id
        else "unassigned"
    )
    return (
        f"project_activity/company_{instance.note.company_id}/{project_segment}/"
        f"note_{instance.note_id}/{uuid.uuid4().hex}{suffix}"
    )


class NoteAttachment(models.Model):
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=note_attachment_path)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255, blank=True)
    size = models.PositiveBigIntegerField()
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="note_attachments",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "pk")

    def __str__(self):
        return self.original_name

    def clean(self):
        super().clean()
        if self.uploaded_by_id and self.uploaded_by.company_id != self.note.company_id:
            raise ValidationError({"uploaded_by": "Uploader must belong to the same company."})


class ActivityItem(models.Model):
    class ItemType(models.TextChoices):
        CHANGE = "change", "Change"
        TASK = "task", "Task"
        QUESTION = "question", "Question"
        DECISION = "decision", "Decision"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        WAITING = "waiting", "Waiting"
        RESOLVED = "resolved", "Resolved"
        CANCELLED = "cancelled", "Cancelled"

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="action_items")
    item_type = models.CharField(
        max_length=20,
        choices=ItemType.choices,
        default=ItemType.TASK,
    )
    title = models.CharField(max_length=500)
    detail = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    due_on = models.DateField(blank=True, null=True)
    order = models.PositiveSmallIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_activity_items",
        blank=True,
        null=True,
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="resolved_activity_items",
        blank=True,
        null=True,
    )
    resolved_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("order", "pk")
        indexes = [models.Index(fields=("status", "due_on"))]

    def clean(self):
        super().clean()
        errors = {}
        if self.created_by_id and self.created_by.company_id != self.note.company_id:
            errors["created_by"] = "Creator must belong to the activity's company."
        if self.resolved_by_id and self.resolved_by.company_id != self.note.company_id:
            errors["resolved_by"] = "Resolver must belong to the activity's company."
        if errors:
            raise ValidationError(errors)

    def mark_status(self, status, *, user=None):
        self.status = status
        if status == self.Status.RESOLVED:
            self.resolved_at = self.resolved_at or timezone.now()
            self.resolved_by = user
        else:
            self.resolved_at = None
            self.resolved_by = None

    def __str__(self):
        return self.title


class ActivityEvent(models.Model):
    class Type(models.TextChoices):
        CREATED = "created", "Activity created"
        UPDATED = "updated", "Activity updated"
        STATUS_CHANGED = "status_changed", "Activity status changed"
        ATTACHMENT_ADDED = "attachment_added", "Attachment added"
        ATTACHMENT_REMOVED = "attachment_removed", "Attachment removed"
        ITEM_ADDED = "item_added", "Action item added"
        ITEM_UPDATED = "item_updated", "Action item updated"
        ITEM_STATUS_CHANGED = "item_status_changed", "Action item status changed"

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=30, choices=Type.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="activity_events",
        blank=True,
        null=True,
    )
    description = models.CharField(max_length=500)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [models.Index(fields=("note", "created_at"))]

    def clean(self):
        super().clean()
        if self.actor_id and self.actor.company_id != self.note.company_id:
            raise ValidationError({"actor": "Actor must belong to the activity's company."})

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Activity history entries are immutable.")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.description
