import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from svix.webhooks import Webhook

from accounts.models import Company
from clients.tests.test_clients import create_client
from documents.delivery_services import (
    deliver_transactional_email,
    email_configuration_status,
)
from documents.models import Document, DocumentDelivery, EmailWebhookEvent
from projects.services import create_project
from projects.tests.test_projects import project_data

RESEND_SETTINGS = override_settings(
    EMAIL_PROVIDER="resend",
    EMAIL_BACKEND="core.email_backends.ResendEmailBackend",
    DEFAULT_FROM_EMAIL="EZ360PM <notifications@mail.example.com>",
    DEFAULT_REPLY_TO_EMAIL="office@example.com",
    RESEND_API_KEY="re_test_key",
    RESEND_WEBHOOK_SECRET="whsec_dGVzdF9yZXNlbmRfd2ViaG9va19zZWNyZXQ=",
    EMAIL_TIMEOUT=10,
)


@RESEND_SETTINGS
class ResendEmailTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Provost Home Design",
            email="office@example.com",
        )
        self.project = create_project(
            company=self.company,
            client=create_client(self.company),
            project_data=project_data(number="RESEND-1"),
        )
        self.document = Document.objects.create(
            company=self.company,
            project=self.project,
            doc_type=Document.Type.PROPOSAL,
            number="P-26-9999",
            status=Document.Status.SENT,
            issue_date=date(2026, 7, 30),
        )

    @patch("core.emailing.requests.post")
    def test_resend_api_returns_provider_id_and_uses_idempotency(self, post):
        post.return_value = SimpleNamespace(
            status_code=200,
            json=lambda: {"id": "email_resend_123"},
        )
        delivery = DocumentDelivery.objects.create(
            document=self.document,
            purpose=DocumentDelivery.Purpose.CLIENT_DOCUMENT,
            recipient_name="Alex Smith",
            recipient_email="alex@example.com",
        )

        result = deliver_transactional_email(
            delivery=delivery,
            subject="Proposal",
            text_body="Text version",
            html_body="<p>HTML version</p>",
            reply_to=("office@example.com",),
        )

        self.assertEqual(result.status, DocumentDelivery.Status.SENT)
        self.assertEqual(result.provider, DocumentDelivery.Provider.RESEND)
        self.assertEqual(result.provider_message_id, "email_resend_123")
        request = post.call_args
        self.assertEqual(request.kwargs["headers"]["Idempotency-Key"], f"delivery/{delivery.pk}")
        self.assertEqual(request.kwargs["json"]["reply_to"], ["office@example.com"])
        self.assertNotIn("re_test_key", str(request.kwargs["json"]))

    @patch("core.emailing.requests.post")
    def test_resend_provider_failure_is_a_safe_durable_code(self, post):
        post.return_value = SimpleNamespace(status_code=403, json=lambda: {})
        delivery = DocumentDelivery.objects.create(
            document=self.document,
            purpose=DocumentDelivery.Purpose.CLIENT_DOCUMENT,
            recipient_name="Alex Smith",
            recipient_email="alex@example.com",
        )

        result = deliver_transactional_email(
            delivery=delivery,
            subject="Proposal",
            text_body="Text version",
            html_body="",
        )

        self.assertEqual(result.status, DocumentDelivery.Status.FAILED)
        self.assertEqual(result.error_code, "resend_http_403")
        self.assertNotIn("re_test_key", result.error_code)

    @patch("core.emailing.requests.post")
    def test_django_backend_sends_framework_email_through_resend(self, post):
        post.return_value = SimpleNamespace(
            status_code=200,
            json=lambda: {"id": "email_password_reset"},
        )
        message = EmailMultiAlternatives(
            subject="Password reset",
            body="Reset your password",
            from_email=None,
            to=["owner@example.com"],
        )

        self.assertEqual(message.send(), 1)
        self.assertEqual(message._ez360_provider_message_id, "email_password_reset")

    def test_configuration_status_requires_api_backend_and_webhook(self):
        status = email_configuration_status()

        self.assertTrue(status["configured"])
        self.assertEqual(status["provider"], "resend")
        self.assertTrue(status["api_key"])
        self.assertTrue(status["webhook_secret"])

    def _signed_webhook(self, event, *, event_id="msg_event_1", timestamp=None):
        timestamp = timestamp or timezone.now()
        payload = json.dumps(event, separators=(",", ":"))
        signature = Webhook(settings.RESEND_WEBHOOK_SECRET).sign(
            event_id,
            timestamp,
            payload,
        )
        return self.client.post(
            reverse("webhooks:resend"),
            data=payload,
            content_type="application/json",
            headers={
                "svix-id": event_id,
                "svix-timestamp": str(int(timestamp.timestamp())),
                "svix-signature": signature,
            },
        )

    def _event(self, delivery, event_type, occurred_at):
        return {
            "type": event_type,
            "created_at": occurred_at.isoformat().replace("+00:00", "Z"),
            "data": {
                "email_id": delivery.provider_message_id,
                "to": [delivery.recipient_email],
                "subject": "Proposal",
            },
        }

    def test_verified_webhook_updates_delivery_and_deduplicates_replays(self):
        delivery = DocumentDelivery.objects.create(
            document=self.document,
            purpose=DocumentDelivery.Purpose.CLIENT_DOCUMENT,
            recipient_name="Alex Smith",
            recipient_email="alex@example.com",
            provider=DocumentDelivery.Provider.RESEND,
            provider_message_id="email_delivery_1",
            status=DocumentDelivery.Status.SENT,
            sent_at=timezone.now(),
        )
        occurred_at = timezone.now()
        event = self._event(delivery, "email.delivered", occurred_at)

        first = self._signed_webhook(event)
        replay = self._signed_webhook(event)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DocumentDelivery.Status.DELIVERED)
        self.assertEqual(EmailWebhookEvent.objects.count(), 1)

    def test_older_webhook_is_stored_without_regressing_status(self):
        delivery = DocumentDelivery.objects.create(
            document=self.document,
            purpose=DocumentDelivery.Purpose.CLIENT_DOCUMENT,
            recipient_name="Alex Smith",
            recipient_email="alex@example.com",
            provider=DocumentDelivery.Provider.RESEND,
            provider_message_id="email_delivery_2",
            status=DocumentDelivery.Status.SENT,
            sent_at=timezone.now(),
        )
        delivered_at = timezone.now()
        self._signed_webhook(
            self._event(delivery, "email.delivered", delivered_at),
            event_id="msg_delivered",
        )
        self._signed_webhook(
            self._event(delivery, "email.sent", delivered_at - timedelta(minutes=1)),
            event_id="msg_older_sent",
        )

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DocumentDelivery.Status.DELIVERED)
        self.assertEqual(EmailWebhookEvent.objects.count(), 2)

    def test_invalid_webhook_signature_is_rejected(self):
        response = self.client.post(
            reverse("webhooks:resend"),
            data="{}",
            content_type="application/json",
            headers={
                "svix-id": "msg_invalid",
                "svix-timestamp": str(int(timezone.now().timestamp())),
                "svix-signature": "v1,invalid",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(EmailWebhookEvent.objects.exists())
