import json
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Company, User
from assistant.draft_tracking import create_document_draft_review, document_snapshot
from assistant.insights import draft_quality_metrics
from assistant.models import (
    AIActionAttempt,
    AIDocumentDraftReview,
    AIInteraction,
)
from clients.tests.test_clients import create_client
from documents.models import DocumentDelivery
from documents.proposal_services import create_proposal, save_proposal_section
from documents.services import delete_draft_document, issue_document, save_line_item
from projects.services import create_project
from projects.tests.test_projects import project_data


@override_settings(AI_ASSISTANT_ENABLED=True, AI_DRAFT_STALE_DAYS=14)
class AIDocumentDraftQualityTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.other_company = Company.objects.create(name="Other Company")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.other_user = User.objects.create_user(
            "other@example.com",
            "Strong-Test-Password-483!",
            company=self.other_company,
        )
        client = create_client(self.company, company_name="Smith Household")
        self.project = create_project(
            company=self.company,
            client=client,
            project_data=project_data(number="2607001", name="Smith Addition"),
        )
        self.interaction = AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="openai",
            model="test-model",
            prompt_summary="draft proposal",
        )

    def _attempt(self, tool_name="prepare_proposal_draft", key="a"):
        return AIActionAttempt.objects.create(
            interaction=self.interaction,
            company=self.company,
            user=self.user,
            tool_name=tool_name,
            risk_level=AIActionAttempt.RiskLevel.FINANCIAL_DRAFT,
            normalized_arguments={},
            preview={"title": "Create draft"},
            confirmation_expires_at=timezone.now() + timedelta(minutes=10),
            idempotency_key=key * 64,
            status=AIActionAttempt.Status.COMPLETED,
        )

    def _proposal(self, number=""):
        proposal = create_proposal(
            company=self.company,
            project=self.project,
            proposal_data={
                "number": number,
                "issue_date": date(2026, 7, 27),
                "terms": "<p>Private customer terms.</p>",
                "notes": "Private internal note.",
            },
        )
        save_proposal_section(
            proposal=proposal,
            heading="Scope of work",
            body="<p>Private project scope text.</p>",
        )
        save_line_item(
            document=proposal,
            line_data={
                "description": "Private residential design description",
                "rate": Decimal("4500.00"),
                "quantity": Decimal("1.00"),
                "tax_rate": Decimal("0"),
            },
        )
        proposal.refresh_from_db()
        return proposal

    def test_snapshot_stores_hashes_not_customer_facing_text(self):
        proposal = self._proposal()

        snapshot = document_snapshot(proposal)
        serialized = json.dumps(snapshot)

        self.assertNotIn("Private customer terms", serialized)
        self.assertNotIn("Private internal note", serialized)
        self.assertNotIn("Private project scope", serialized)
        self.assertNotIn("Private residential design", serialized)
        self.assertEqual(snapshot["total"], "4500.00")
        self.assertEqual(len(snapshot["body_sections"]), 1)
        self.assertEqual(len(snapshot["line_items"]), 1)

    def test_revision_and_issue_are_recorded_from_normal_document_services(self):
        proposal = self._proposal()
        review = create_document_draft_review(
            action_attempt=self._attempt(),
            document=proposal,
        )

        proposal.terms = "<p>Revised customer terms.</p>"
        with self.captureOnCommitCallbacks(execute=True):
            proposal.save(update_fields=["terms", "updated_at"])

        review.refresh_from_db()
        self.assertEqual(review.revision_count, 1)
        self.assertIn("terms", review.changed_fields)
        self.assertEqual(review.outcome, AIDocumentDraftReview.Outcome.ACTIVE)

        with self.captureOnCommitCallbacks(execute=True):
            issue_document(document=proposal)

        review.refresh_from_db()
        self.assertEqual(
            review.outcome,
            AIDocumentDraftReview.Outcome.EDITED_THEN_USED,
        )
        self.assertIsNotNone(review.issued_at)

    def test_unedited_issue_is_classified_as_used_as_is(self):
        proposal = self._proposal()
        review = create_document_draft_review(
            action_attempt=self._attempt(key="b"),
            document=proposal,
        )

        with self.captureOnCommitCallbacks(execute=True):
            issue_document(document=proposal)

        review.refresh_from_db()
        self.assertEqual(review.revision_count, 0)
        self.assertEqual(review.outcome, AIDocumentDraftReview.Outcome.USED_AS_IS)

    def test_deleted_ai_draft_is_preserved_as_metadata_only_abandonment(self):
        proposal = self._proposal()
        review = create_document_draft_review(
            action_attempt=self._attempt(key="c"),
            document=proposal,
        )

        delete_draft_document(document=proposal)

        review.refresh_from_db()
        self.assertIsNone(review.document_id)
        self.assertIsNotNone(review.deleted_at)
        self.assertEqual(review.outcome, AIDocumentDraftReview.Outcome.ABANDONED)

    def test_first_successful_delivery_is_recorded(self):
        proposal = self._proposal()
        review = create_document_draft_review(
            action_attempt=self._attempt(key="d"),
            document=proposal,
        )
        sent_at = timezone.now()

        with self.captureOnCommitCallbacks(execute=True):
            DocumentDelivery.objects.create(
                document=proposal,
                recipient_name="Alex Smith",
                recipient_email="alex@example.com",
                subject="Proposal",
                status=DocumentDelivery.Status.SENT,
                sent_at=sent_at,
            )

        review.refresh_from_db()
        self.assertEqual(review.first_delivery_at, sent_at)

    def test_metrics_and_csv_export_are_company_scoped(self):
        proposal = self._proposal()
        create_document_draft_review(
            action_attempt=self._attempt(key="e"),
            document=proposal,
        )
        other_interaction = AIInteraction.objects.create(
            company=self.other_company,
            user=self.other_user,
            provider="openai",
            model="test-model",
            prompt_summary="hidden",
        )
        other_attempt = AIActionAttempt.objects.create(
            interaction=other_interaction,
            company=self.other_company,
            user=self.other_user,
            tool_name="prepare_proposal_draft",
            risk_level=AIActionAttempt.RiskLevel.FINANCIAL_DRAFT,
            normalized_arguments={},
            preview={},
            confirmation_expires_at=timezone.now() + timedelta(minutes=10),
            idempotency_key="f" * 64,
            status=AIActionAttempt.Status.COMPLETED,
        )
        other_client = create_client(self.other_company, company_name="Hidden")
        other_project = create_project(
            company=self.other_company,
            client=other_client,
            project_data=project_data(number="HIDDEN", name="Hidden Project"),
        )
        other_document = create_proposal(
            company=self.other_company,
            project=other_project,
            proposal_data={
                # Human-readable document sequences are company-scoped, so use a
                # distinct value to make the export isolation assertion meaningful.
                "number": "OTHER-PROPOSAL",
                "issue_date": date(2026, 7, 27),
                "terms": "",
                "notes": "",
            },
        )
        create_document_draft_review(
            action_attempt=other_attempt,
            document=other_document,
        )

        metrics = draft_quality_metrics(self.user, days=90)
        self.assertEqual(metrics["total"], 1)

        self.client.force_login(self.user)
        response = self.client.get(reverse("assistant:draft-quality-export"))
        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn(proposal.number, content)
        self.assertNotIn(other_document.number, content)
