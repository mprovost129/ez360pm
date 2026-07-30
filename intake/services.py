from django.db import transaction
from django.db.models import Max

from .models import ActivityItem, NoteAttachment


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
    return item
