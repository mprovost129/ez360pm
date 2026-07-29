from types import SimpleNamespace
from unittest.mock import call, patch

from django.test import RequestFactory, TestCase, override_settings

from accounts.models import Company, User
from assistant import signals
from assistant.context_processors import assistant_status
from assistant.models import AICompanySettings, AIUserAccess
from assistant.policies import get_company_policy
from documents.models import DocumentDelivery


class LazyAIProvisioningTests(TestCase):
    def _create_company_and_user(self):
        company = Company.objects.create(name="Provost Home Design")
        user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=company,
            is_staff=True,
        )
        return company, user

    @override_settings(AI_ASSISTANT_ENABLED=False)
    def test_company_and_user_creation_do_not_write_assistant_tables_when_disabled(self):
        self._create_company_and_user()

        self.assertFalse(AICompanySettings.objects.exists())
        self.assertFalse(AIUserAccess.objects.exists())

    @override_settings(
        AI_ASSISTANT_ENABLED=True,
        AI_COMPANY_DEFAULT_ENABLED=True,
        AI_COMPANY_DEFAULT_PRIVACY_ACKNOWLEDGED=True,
        AI_COMPANY_DEFAULT_ACCESS_MODE="all_users",
    )
    def test_company_and_user_creation_remain_lazy_when_platform_ai_is_enabled(self):
        company, user = self._create_company_and_user()

        self.assertFalse(AICompanySettings.objects.exists())
        self.assertFalse(AIUserAccess.objects.exists())

        request = RequestFactory().get("/projects/")
        request.user = user
        context = assistant_status(request)

        self.assertTrue(context["ai_assistant_enabled"])
        self.assertIsNone(context["ai_company_settings"].pk)
        self.assertFalse(AICompanySettings.objects.exists())
        self.assertFalse(AIUserAccess.objects.exists())

        policy = get_company_policy(company)
        self.assertIsNotNone(policy.pk)
        self.assertEqual(AICompanySettings.objects.count(), 1)
        self.assertFalse(AIUserAccess.objects.exists())

    @override_settings(
        AI_ASSISTANT_ENABLED=True,
        AI_COMPANY_DEFAULT_ENABLED=True,
        AI_COMPANY_DEFAULT_PRIVACY_ACKNOWLEDGED=True,
        AI_COMPANY_DEFAULT_ACCESS_MODE="selected_users",
    )
    def test_selected_user_access_requires_an_explicit_grant(self):
        company, user = self._create_company_and_user()
        policy = get_company_policy(company)

        self.assertEqual(policy.access_mode, AICompanySettings.AccessMode.SELECTED_USERS)
        self.assertFalse(AIUserAccess.objects.filter(user=user).exists())


class OptionalDraftTrackingSignalTests(TestCase):
    @override_settings(AI_ASSISTANT_ENABLED=False)
    @patch("assistant.signals.mark_draft_deleted")
    @patch("assistant.signals.schedule_delivery_state")
    @patch("assistant.signals.schedule_document_state")
    def test_disabled_platform_skips_all_ai_draft_tracking_hooks(
        self, schedule_document_state, schedule_delivery_state, mark_draft_deleted
    ):
        signals.track_ai_document_change(None, SimpleNamespace(pk=11))
        signals.track_ai_line_item_change(
            None, SimpleNamespace(document_id=12)
        )
        signals.track_ai_credit_change(
            None, SimpleNamespace(destination_invoice_id=13)
        )
        signals.track_ai_document_delivery(
            None,
            SimpleNamespace(
                status=DocumentDelivery.Status.SENT,
                document_id=14,
                sent_at=None,
            ),
        )
        signals.track_ai_draft_deletion(None, SimpleNamespace(pk=15))

        schedule_document_state.assert_not_called()
        schedule_delivery_state.assert_not_called()
        mark_draft_deleted.assert_not_called()

    @override_settings(AI_ASSISTANT_ENABLED=True)
    @patch("assistant.signals.mark_draft_deleted")
    @patch("assistant.signals.schedule_delivery_state")
    @patch("assistant.signals.schedule_document_state")
    def test_enabled_platform_keeps_ai_draft_tracking_hooks_active(
        self, schedule_document_state, schedule_delivery_state, mark_draft_deleted
    ):
        signals.track_ai_document_change(None, SimpleNamespace(pk=21))
        signals.track_ai_line_item_change(
            None, SimpleNamespace(document_id=22)
        )
        signals.track_ai_credit_change(
            None, SimpleNamespace(destination_invoice_id=23)
        )
        signals.track_ai_document_delivery(
            None,
            SimpleNamespace(
                status=DocumentDelivery.Status.SENT,
                document_id=24,
                sent_at=None,
            ),
        )
        signals.track_ai_draft_deletion(None, SimpleNamespace(pk=25))

        self.assertEqual(
            schedule_document_state.call_args_list,
            [call(21), call(22), call(23)],
        )
        schedule_delivery_state.assert_called_once_with(24, sent_at=None)
        mark_draft_deleted.assert_called_once()
