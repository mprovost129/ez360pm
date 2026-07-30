from pathlib import Path

from django import forms

MAX_NOTE_ATTACHMENT_BYTES = 20 * 1024 * 1024
NOTE_ATTACHMENT_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".eml",
    ".heic",
    ".heif",
    ".jpeg",
    ".jpg",
    ".msg",
    ".pdf",
    ".png",
    ".txt",
    ".webp",
    ".xls",
    ".xlsx",
}
NOTE_ATTACHMENT_CONTENT_TYPES = {
    "application/msword",
    "application/octet-stream",
    "application/pdf",
    "application/vnd.ms-excel",
    "application/vnd.ms-outlook",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/heic",
    "image/heif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "message/rfc822",
    "text/csv",
    "text/plain",
}


def validate_note_attachment(uploaded_file):
    if uploaded_file.size > MAX_NOTE_ATTACHMENT_BYTES:
        raise forms.ValidationError("Attachments must be 20 MB or smaller.")
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix not in NOTE_ATTACHMENT_EXTENSIONS:
        raise forms.ValidationError(
            "Upload an email, PDF, Office document, text file, or supported image."
        )
    content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    if content_type and content_type not in NOTE_ATTACHMENT_CONTENT_TYPES:
        raise forms.ValidationError("The reported attachment type is not allowed.")
