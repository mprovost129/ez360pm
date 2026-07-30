"""Django email backend that delivers framework messages through Resend."""

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

from .emailing import (
    EmailAttachment,
    EmailDeliveryError,
    ResendProvider,
    TransactionalEmail,
)


def _message_html(message):
    for alternative in getattr(message, "alternatives", ()):
        if alternative.mimetype == "text/html":
            return alternative.content
    return ""


def _message_attachments(message):
    attachments = []
    for attachment in getattr(message, "attachments", ()):
        filename = getattr(attachment, "filename", None)
        content = getattr(attachment, "content", None)
        mimetype = getattr(attachment, "mimetype", None)
        if filename is None and isinstance(attachment, tuple):
            filename, content, mimetype = attachment
        if not filename or content is None:
            raise EmailDeliveryError("resend_attachment_unsupported")
        if isinstance(content, str):
            content = content.encode("utf-8")
        attachments.append(
            EmailAttachment(
                filename=filename,
                content=bytes(content),
                content_type=mimetype or "application/octet-stream",
            )
        )
    return tuple(attachments)


class ResendEmailBackend(BaseEmailBackend):
    """Allow Django-owned email flows to share the Resend HTTPS transport."""

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        sent = 0
        provider = ResendProvider()
        for message in email_messages:
            try:
                result = provider.send(
                    TransactionalEmail(
                        subject=message.subject,
                        text_body=message.body,
                        html_body=_message_html(message),
                        from_email=message.from_email or settings.DEFAULT_FROM_EMAIL,
                        to=tuple(message.to),
                        cc=tuple(message.cc),
                        bcc=tuple(message.bcc),
                        reply_to=(
                            tuple(message.reply_to)
                            or (
                                (settings.DEFAULT_REPLY_TO_EMAIL,)
                                if settings.DEFAULT_REPLY_TO_EMAIL
                                else ()
                            )
                        ),
                        attachments=_message_attachments(message),
                        headers=dict(message.extra_headers),
                    )
                )
            except EmailDeliveryError:
                if not self.fail_silently:
                    raise
            else:
                message._ez360_provider_message_id = result.message_id
                sent += 1
        return sent
