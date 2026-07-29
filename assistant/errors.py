"""Consistent user-facing error formatting for assistant workflows."""


def validation_error_message(exc):
    """Return Django validation text without Python list/dict formatting."""

    messages = getattr(exc, "messages", None)
    if messages:
        return " ".join(str(message) for message in messages)
    message_dict = getattr(exc, "message_dict", None)
    if message_dict:
        flattened = []
        for field, field_messages in message_dict.items():
            label = str(field).replace("_", " ").title()
            flattened.extend(f"{label}: {message}" for message in field_messages)
        if flattened:
            return " ".join(flattened)
    return str(exc)
