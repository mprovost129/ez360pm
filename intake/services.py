from django.db import transaction
from django.db.models import Max

from .models import ActivityEvent, ActivityItem, Note, NoteAttachment


def record_activity_event(*, note, event_type, description, actor=None, metadata=None):
    event = ActivityEvent(
        note=note,
        event_type=event_type,
        actor=actor,
        description=description[:500],
        metadata=metadata or {},
    )
    event.full_clean()
    event.save()
    return event


@transaction.atomic
def add_note_attachment(*, note, uploaded_file, uploaded_by=None):
    original_name = uploaded_file.name.replace("\\", "/").rsplit("/", 1)[-1][:255]
    attachment = NoteAttachment(
        note=note,
        file=uploaded_file,
        original_name=original_name,
        content_type=(getattr(uploaded_file, "content_type", "") or "")[:255],
        size=uploaded_file.size,
        uploaded_by=uploaded_by,
    )
    attachment.full_clean(exclude=("file",))
    attachment.save()
    record_activity_event(
        note=note,
        event_type=ActivityEvent.Type.ATTACHMENT_ADDED,
        description=f"Attachment added: {original_name}",
        actor=uploaded_by,
        metadata={"attachment_id": attachment.pk, "file_name": original_name},
    )
    return attachment


@transaction.atomic
def create_activity_item(*, note, data, created_by=None):
    note = note.__class__.objects.select_for_update().get(pk=note.pk)
    next_order = note.action_items.aggregate(value=Max("order"))["value"] or 0
    item = ActivityItem(
        note=note,
        order=next_order + 1,
        created_by=created_by,
        **data,
    )
    item.mark_status(item.status, user=created_by)
    item.full_clean()
    item.save()
    record_activity_event(
        note=note,
        event_type=ActivityEvent.Type.ITEM_ADDED,
        description=f"Action item added: {item.title}",
        actor=created_by,
        metadata={"item_id": item.pk, "item_type": item.item_type},
    )
    return item


@transaction.atomic
def create_project_activity(*, project, data, action_items, created_by=None):
    note = Note(
        company=project.company,
        project=project,
        client=project.client,
        created_by=created_by,
        **data,
    )
    note.full_clean()
    note.save()
    record_activity_event(
        note=note,
        event_type=ActivityEvent.Type.CREATED,
        description="Project activity created.",
        actor=created_by,
        metadata={"source": note.source_type, "activity_type": note.activity_type},
    )
    for item_data in action_items:
        create_activity_item(note=note, data=item_data, created_by=created_by)
    return note
