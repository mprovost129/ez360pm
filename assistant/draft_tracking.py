"""Metadata-only quality tracking for AI-created document drafts.

The tracker never stores proposal sections, invoice descriptions, terms, or notes.
It stores hashes and structural/financial metadata so the team can determine
whether AI drafts are revised, used as-is, or abandoned.
"""

import hashlib
import json
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from documents.models import Document

from .models import AIDocumentDraftReview

DRAFT_TOOL_NAMES = {
    "prepare_proposal_draft",
    "prepare_retainer_invoice_draft",
    "prepare_final_invoice_draft",
}

REVISION_TOOL_NAMES = {
    "revise_proposal_draft",
    "revise_invoice_draft",
}

TRACKED_FIELDS = (
    "number",
    "issue_date",
    "due_date",
    "accept_payments",
    "terms",
    "notes",
    "body_sections",
    "line_items",
    "subtotal",
    "tax_total",
    "credit_total",
    "total",
)


def _hash_text(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _money(value):
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def _canonical_hash(payload):
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        cls=DjangoJSONEncoder,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def document_snapshot(document):
    """Return a non-content snapshot suitable for long-lived analytics."""
    document = (
        Document.objects.select_related("company", "project")
        .prefetch_related("line_items__time_entries")
        .get(pk=document.pk)
    )
    sections = [
        {
            "position": index,
            "heading_hash": _hash_text(str(section.get("heading", ""))),
            "body_hash": _hash_text(str(section.get("body", ""))),
        }
        for index, section in enumerate(document.body_sections or [])
        if isinstance(section, dict)
    ]
    lines = [
        {
            "order": line.order,
            "description_hash": _hash_text(line.description),
            "rate": str(line.rate),
            "quantity": str(line.quantity),
            "tax_rate": str(line.tax_rate),
            "line_total": _money(line.line_total),
            "time_entry_count": len(line._prefetched_objects_cache.get("time_entries", [])),
        }
        for line in document.line_items.all()
    ]
    return {
        "number": document.number,
        "issue_date": document.issue_date.isoformat() if document.issue_date else None,
        "due_date": document.due_date.isoformat() if document.due_date else None,
        "accept_payments": bool(document.accept_payments),
        "terms": _hash_text(document.terms),
        "notes": _hash_text(document.notes),
        "body_sections": sections,
        "line_items": lines,
        "subtotal": _money(document.subtotal),
        "tax_total": _money(document.tax_total),
        "credit_total": _money(document.credit_total),
        "total": _money(document.total),
    }


def snapshot_hash(snapshot):
    return _canonical_hash(snapshot)


def changed_fields(initial, current):
    return [field for field in TRACKED_FIELDS if initial.get(field) != current.get(field)]


def create_document_draft_review(*, action_attempt, document):
    if action_attempt.tool_name not in DRAFT_TOOL_NAMES:
        return None
    if action_attempt.company_id != document.company_id:
        raise ValueError("AI draft tracking cannot cross company boundaries.")
    snapshot = document_snapshot(document)
    digest = snapshot_hash(snapshot)
    review, _created = AIDocumentDraftReview.objects.get_or_create(
        action_attempt=action_attempt,
        defaults={
            "company": action_attempt.company,
            "user": action_attempt.user,
            "document": document,
            "document_type": document.doc_type,
            "document_number": document.number,
            "initial_snapshot": snapshot,
            "latest_snapshot": snapshot,
            "initial_snapshot_hash": digest,
            "latest_snapshot_hash": digest,
        },
    )
    return review


def _create_revision_review(*, action_attempt, document, initial_snapshot):
    existing = (
        AIDocumentDraftReview.objects.filter(document=document, deleted_at__isnull=True)
        .order_by("created_at", "pk")
        .first()
    )
    if existing is not None:
        return record_document_state(document.pk)

    current_snapshot = document_snapshot(document)
    initial_digest = snapshot_hash(initial_snapshot)
    current_digest = snapshot_hash(current_snapshot)
    now = timezone.now()
    fields = changed_fields(initial_snapshot, current_snapshot)
    review, _created = AIDocumentDraftReview.objects.get_or_create(
        action_attempt=action_attempt,
        defaults={
            "company": action_attempt.company,
            "user": action_attempt.user,
            "document": document,
            "document_type": document.doc_type,
            "document_number": document.number,
            "initial_snapshot": initial_snapshot,
            "latest_snapshot": current_snapshot,
            "initial_snapshot_hash": initial_digest,
            "latest_snapshot_hash": current_digest,
            "changed_fields": fields,
            "revision_count": 1 if fields else 0,
            "first_revised_at": now if fields else None,
            "last_revised_at": now if fields else None,
        },
    )
    return review


def track_completed_draft_action(*, action_attempt, result):
    if not isinstance(result, dict):
        return None
    created_document_id = result.get("_created_document_id")
    if created_document_id and action_attempt.tool_name in DRAFT_TOOL_NAMES:
        document = Document.objects.for_company(action_attempt.company).get(
            pk=created_document_id
        )
        return create_document_draft_review(
            action_attempt=action_attempt,
            document=document,
        )

    revised_document_id = result.get("_revised_document_id")
    initial_snapshot = result.get("_initial_document_snapshot")
    if (
        revised_document_id
        and isinstance(initial_snapshot, dict)
        and action_attempt.tool_name in REVISION_TOOL_NAMES
    ):
        document = Document.objects.for_company(action_attempt.company).get(
            pk=revised_document_id
        )
        return _create_revision_review(
            action_attempt=action_attempt,
            document=document,
            initial_snapshot=initial_snapshot,
        )
    return None


def record_document_state(document_id):
    review = (
        AIDocumentDraftReview.objects.filter(document_id=document_id)
        .select_related("document")
        .first()
    )
    if review is None or review.document is None:
        return None
    document = review.document
    snapshot = document_snapshot(document)
    digest = snapshot_hash(snapshot)
    now = timezone.now()
    update_fields = []

    if review.document_number != document.number:
        review.document_number = document.number
        update_fields.append("document_number")

    if digest != review.latest_snapshot_hash:
        review.latest_snapshot = snapshot
        review.latest_snapshot_hash = digest
        review.changed_fields = changed_fields(review.initial_snapshot, snapshot)
        review.revision_count += 1
        if review.first_revised_at is None:
            review.first_revised_at = now
            update_fields.append("first_revised_at")
        review.last_revised_at = now
        update_fields.extend(
            [
                "latest_snapshot",
                "latest_snapshot_hash",
                "changed_fields",
                "revision_count",
                "last_revised_at",
            ]
        )

    if document.status != Document.Status.DRAFT and review.issued_at is None:
        review.issued_at = document.sent_at or now
        review.outcome = (
            AIDocumentDraftReview.Outcome.EDITED_THEN_USED
            if review.revision_count
            else AIDocumentDraftReview.Outcome.USED_AS_IS
        )
        update_fields.extend(["issued_at", "outcome"])

    if update_fields:
        review.save(update_fields=list(dict.fromkeys(update_fields + ["updated_at"])))
    return review


def schedule_document_state(document_id):
    if document_id:
        transaction.on_commit(lambda: record_document_state(document_id))


def record_delivery_state(document_id, *, sent_at=None):
    review = AIDocumentDraftReview.objects.filter(document_id=document_id).first()
    if review is None or review.first_delivery_at is not None:
        return review
    review.first_delivery_at = sent_at or timezone.now()
    review.save(update_fields=["first_delivery_at", "updated_at"])
    return review


def schedule_delivery_state(document_id, *, sent_at=None):
    if document_id:
        transaction.on_commit(
            lambda: record_delivery_state(document_id, sent_at=sent_at)
        )


def mark_draft_deleted(document):
    review = AIDocumentDraftReview.objects.filter(document_id=document.pk).first()
    if review is None:
        return None
    review.document_number = document.number
    review.document_type = document.doc_type
    review.deleted_at = timezone.now()
    if document.status == Document.Status.DRAFT:
        review.outcome = AIDocumentDraftReview.Outcome.ABANDONED
    review.save(
        update_fields=[
            "document_number",
            "document_type",
            "deleted_at",
            "outcome",
            "updated_at",
        ]
    )
    return review
