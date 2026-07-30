from django.db import transaction

from .models import NoteAttachment


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
