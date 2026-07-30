"""Provider-neutral transactional email delivery.

Application services call ``send_transactional_email`` so provider selection,
safe error codes, idempotency, and provider identifiers behave consistently.
The custom Django backend in ``core.email_backends`` reuses ``ResendProvider``
for framework-owned messages such as password reset email.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

import requests
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

RESEND_EMAILS_URL = "https://api.resend.com/emails"


class EmailDeliveryError(Exception):
    """A provider-safe delivery error suitable for durable error codes."""

    def __init__(self, code):
        self.code = str(code)[:100]
        super().__init__(self.code)


@dataclass(frozen=True)
class EmailAttachment:
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


@dataclass(frozen=True)
class TransactionalEmail:
    subject: str
    text_body: str
    to: tuple[str, ...]
    html_body: str = ""
    from_email: str = ""
    reply_to: tuple[str, ...] = ()
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()
    attachments: tuple[EmailAttachment, ...] = ()
    idempotency_key: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EmailSendResult:
    provider: str
    message_id: str = ""


class DjangoEmailProvider:
    name = "django"

    def send(self, email):
        message = EmailMultiAlternatives(
            subject=email.subject,
            body=email.text_body,
            from_email=email.from_email or settings.DEFAULT_FROM_EMAIL,
            to=list(email.to),
            cc=list(email.cc),
            bcc=list(email.bcc),
            reply_to=list(email.reply_to),
            headers=dict(email.headers),
        )
        if email.html_body:
            message.attach_alternative(email.html_body, "text/html")
        for attachment in email.attachments:
            message.attach(
                attachment.filename,
                attachment.content,
                attachment.content_type,
            )
        try:
            sent_count = message.send(fail_silently=False)
        except Exception as exc:  # Django backends raise provider-specific errors.
            raise EmailDeliveryError(exc.__class__.__name__.lower()) from exc
        if sent_count != 1:
            raise EmailDeliveryError("provider_did_not_confirm_send")
        return EmailSendResult(provider=self.name)


class ResendProvider:
    name = "resend"

    def __init__(self, *, api_key=None, timeout=None):
        self.api_key = settings.RESEND_API_KEY if api_key is None else api_key
        self.timeout = settings.EMAIL_TIMEOUT if timeout is None else timeout

    def send(self, email):
        if not self.api_key:
            raise EmailDeliveryError("resend_api_key_missing")
        payload = {
            "from": email.from_email or settings.DEFAULT_FROM_EMAIL,
            "to": list(email.to),
            "subject": email.subject,
            "text": email.text_body,
        }
        if email.html_body:
            payload["html"] = email.html_body
        if email.reply_to:
            payload["reply_to"] = list(email.reply_to)
        if email.cc:
            payload["cc"] = list(email.cc)
        if email.bcc:
            payload["bcc"] = list(email.bcc)
        if email.headers:
            payload["headers"] = dict(email.headers)
        if email.attachments:
            payload["attachments"] = [
                {
                    "filename": attachment.filename,
                    "content": base64.b64encode(attachment.content).decode("ascii"),
                    "content_type": attachment.content_type,
                }
                for attachment in email.attachments
            ]
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "EZ360PM/1.0",
        }
        if email.idempotency_key:
            headers["Idempotency-Key"] = email.idempotency_key[:256]
        try:
            response = requests.post(
                RESEND_EMAILS_URL,
                headers=headers,
                json=payload,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.Timeout as exc:
            raise EmailDeliveryError("resend_timeout") from exc
        except requests.RequestException as exc:
            raise EmailDeliveryError("resend_connection_error") from exc
        if response.status_code not in {200, 201}:
            raise EmailDeliveryError(f"resend_http_{response.status_code}")
        try:
            message_id = str(response.json()["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EmailDeliveryError("resend_invalid_response") from exc
        if not message_id:
            raise EmailDeliveryError("resend_invalid_response")
        return EmailSendResult(provider=self.name, message_id=message_id[:255])


def configured_email_provider():
    provider = settings.EMAIL_PROVIDER.strip().lower()
    if provider == "resend":
        return ResendProvider()
    if provider == "django":
        return DjangoEmailProvider()
    raise EmailDeliveryError("email_provider_invalid")


def send_transactional_email(email):
    return configured_email_provider().send(email)
