from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.urls import reverse
from django.utils import timezone

from clients.models import Client
from documents.models import Document
from projects.models import Project, TimeEntry

from .models import (
    AIActionAttempt,
    AIDocumentDraftReview,
    AIEvent,
    AIInsightDismissal,
    AIInteraction,
)
from .policies import (
    current_month_usage,
    effective_cost_limit,
    get_company_policy,
    risk_allowed,
)

SUGGESTION_LIBRARY = {
    "create_note": (
        "Capture a quick note",
        "Create a quick note. Ask me for the note text.",
    ),
    "start_timer": (
        "Start a project timer",
        "Start a timer for a project. Ask me which project and what I am working on.",
    ),
    "stop_timer": (
        "Stop my timer",
        "Stop my active timer after showing me the current project and elapsed time.",
    ),
    "create_client": (
        "Add a client",
        "Create a new client and primary contact. Ask for missing fields with a template beginning 'Create this client:'. Use the built-in duplicate check before confirmation.",
    ),
    "create_project": (
        "Open a lead project",
        "Create a lead project for an existing client. Show all project and billing fields before saving.",
    ),
    "prepare_proposal_draft": (
        "Draft a proposal",
        "Prepare an editable proposal draft for a project. Ask me to identify the project and show scope and pricing before creating it.",
    ),
    "prepare_final_invoice_draft": (
        "Draft a final invoice",
        "Prepare a final invoice draft using eligible unbilled time and available retainer credit. Show the complete draft first.",
    ),
    "issue_and_send_document": (
        "Send a reviewed document",
        "Review a draft document and prepare to issue and email it to an eligible client contact. Show the exact final confirmation first.",
    ),
    "send_document_follow_up": (
        "Draft a client follow-up",
        "Prepare one reviewed follow-up for an open proposal, retainer, or invoice. Ask me which document and show the exact recipient, subject, and message before sending.",
    ),
    "record_manual_payment": (
        "Record a manual payment",
        "Prepare to record a verified check, cash, or other manual payment. Ask me for the invoice and payment details.",
    ),
    "get_attention_summary": (
        "Review what needs attention",
        "What needs my attention today?",
    ),
    "get_revenue_summary": (
        "Review revenue and fees",
        "How much revenue did I receive this year by payment method, and how much did Stripe deduct in fees?",
    ),
}

SUGGESTION_RISKS = {
    "create_note": "low_write",
    "start_timer": "low_write",
    "stop_timer": "low_write",
    "create_client": "structured_write",
    "create_project": "structured_write",
    "prepare_proposal_draft": "financial_draft",
    "prepare_final_invoice_draft": "financial_draft",
    "issue_and_send_document": "external_commit",
    "send_document_follow_up": "external_commit",
    "record_manual_payment": "external_commit",
    "get_attention_summary": "read",
    "get_revenue_summary": "read",
}

DEFAULT_SUGGESTIONS = [
    "get_attention_summary",
    "get_revenue_summary",
    "start_timer",
    "create_note",
]


def record_event(
    *,
    user,
    event_type,
    capability="",
    interaction=None,
    action_attempt=None,
    metadata=None,
):
    safe_metadata = {}
    for key, value in (metadata or {}).items():
        if key in {"reason", "suggestion_id", "insight_key", "error_code", "tool_name"}:
            safe_metadata[key] = str(value)[:255]
    return AIEvent.objects.create(
        company=user.company,
        user=user,
        interaction=interaction,
        action_attempt=action_attempt,
        event_type=event_type,
        capability=capability[:100],
        metadata=safe_metadata,
    )


def _is_dismissed(user, key):
    return AIInsightDismissal.objects.filter(
        company=user.company,
        user=user,
        insight_key=key,
        dismissed_until__gt=timezone.now(),
    ).exists()


def _add(items, user, *, key, title, summary, url, priority):
    if not _is_dismissed(user, key):
        items.append(
            {
                "key": key,
                "title": title,
                "summary": summary,
                "url": url,
                "priority": priority,
            }
        )


def proactive_insights(user):
    company = user.company
    now = timezone.now()
    today = timezone.localdate()
    items = []

    active_timer = (
        TimeEntry.objects.filter(company=company, user=user, end_time__isnull=True)
        .select_related("project")
        .first()
    )
    if active_timer:
        age = now - active_timer.start_time
        threshold = timedelta(hours=settings.AI_FORGOTTEN_TIMER_HOURS)
        if age >= threshold:
            hours = max(age.total_seconds() / 3600, 0)
            _add(
                items,
                user,
                key=f"forgotten_timer:{active_timer.pk}",
                title="Timer may have been left running",
                summary=f"{active_timer.project.number} has been active for about {hours:.1f} hours.",
                url=reverse("projects:detail", kwargs={"pk": active_timer.project_id}),
                priority=100,
            )

    stale_cutoff = now - timedelta(days=settings.AI_STALE_LEAD_DAYS)
    for project in (
        Project.objects.for_company(company)
        .filter(status=Project.Status.LEAD, updated_at__lt=stale_cutoff)
        .select_related("client")
        .order_by("updated_at")[:3]
    ):
        days = max((today - project.updated_at.date()).days, 0)
        _add(
            items,
            user,
            key=f"stale_lead:{project.pk}:{project.updated_at.date().isoformat()}",
            title="Lead may need follow-up",
            summary=f"{project.number} — {project.name} has not changed in {days} days.",
            url=reverse("projects:detail", kwargs={"pk": project.pk}),
            priority=80,
        )

    funded_retainer = Document.objects.filter(
        company=company,
        project_id=OuterRef("pk"),
        doc_type=Document.Type.INVOICE,
        invoice_kind=Document.InvoiceKind.RETAINER,
        status__in=[Document.Status.PARTIALLY_PAID, Document.Status.PAID],
    )
    waiting_projects = (
        Project.objects.for_company(company)
        .filter(status=Project.Status.APPROVED)
        .annotate(has_funded_retainer=Exists(funded_retainer))
        .filter(has_funded_retainer=False)
        .select_related("client")
        .order_by("updated_at")[:3]
    )
    for project in waiting_projects:
        _add(
            items,
            user,
            key=f"approved_without_retainer:{project.pk}",
            title="Approved project is waiting for a retainer",
            summary=f"{project.number} — {project.name} is approved but has no paid or partially paid retainer.",
            url=reverse("projects:detail", kwargs={"pk": project.pk}),
            priority=90,
        )

    completed_unbilled = (
        Project.objects.for_company(company)
        .filter(
            status=Project.Status.COMPLETED,
            time_entries__end_time__isnull=False,
            time_entries__billable=True,
            time_entries__status=TimeEntry.Status.LOGGED,
            time_entries__line_item__isnull=True,
        )
        .distinct()
        .order_by("updated_at")[:3]
    )
    for project in completed_unbilled:
        count = project.time_entries.filter(
            end_time__isnull=False,
            billable=True,
            status=TimeEntry.Status.LOGGED,
            line_item__isnull=True,
        ).count()
        _add(
            items,
            user,
            key=f"completed_unbilled:{project.pk}",
            title="Completed project still has unbilled time",
            summary=f"{project.number} — {project.name} has {count} unbilled billable time entr{'y' if count == 1 else 'ies'}.",
            url=reverse("projects:detail", kwargs={"pk": project.pk}),
            priority=95,
        )

    clients_missing_email = (
        Client.objects.for_company(company)
        .annotate(email_count=Count("contacts", filter=~Q(contacts__email="")))
        .filter(email_count=0)
        .order_by("created_at")[:2]
    )
    for client in clients_missing_email:
        _add(
            items,
            user,
            key=f"client_missing_email:{client.pk}",
            title="Client has no email address",
            summary=f"{client.display_name} cannot receive proposals or invoices until a contact email is added.",
            url=reverse("clients:detail", kwargs={"pk": client.pk}),
            priority=70,
        )

    items.sort(key=lambda item: (-item["priority"], item["title"]))
    return items[: settings.AI_PROACTIVE_MAX_ITEMS]


def dismiss_insight(*, user, insight_key):
    until = timezone.now() + timedelta(days=settings.AI_PROACTIVE_DISMISS_DAYS)
    AIInsightDismissal.objects.update_or_create(
        company=user.company,
        user=user,
        insight_key=insight_key[:255],
        defaults={"dismissed_until": until},
    )
    record_event(
        user=user,
        event_type=AIEvent.Type.INSIGHT_DISMISSED,
        capability="proactive_insight",
        metadata={"insight_key": insight_key},
    )
    return until


def command_suggestions(user, limit=6, policy=None):
    policy = policy or get_company_policy(user.company)
    allowed_names = [
        name
        for name in SUGGESTION_LIBRARY
        if risk_allowed(policy, SUGGESTION_RISKS.get(name, "read"))
    ]
    counts = dict(
        AIActionAttempt.objects.filter(
            company=user.company,
            user=user,
            status=AIActionAttempt.Status.COMPLETED,
            tool_name__in=allowed_names,
        )
        .values_list("tool_name")
        .annotate(total=Count("id"))
        .order_by("-total")[:limit]
    )
    used = list(counts)
    ordered = used + [
        name
        for name in DEFAULT_SUGGESTIONS
        if name in allowed_names and name not in used
    ]
    ordered += [name for name in allowed_names if name not in ordered]
    return [
        {
            "id": name,
            "label": SUGGESTION_LIBRARY[name][0],
            "prompt": SUGGESTION_LIBRARY[name][1],
        }
        for name in ordered[:limit]
    ]


def usage_metrics(user, days=30, policy=None):
    policy = policy or get_company_policy(user.company)
    start = timezone.now() - timedelta(days=days)
    interactions = AIInteraction.objects.filter(
        company=user.company, created_at__gte=start
    )
    actions = AIActionAttempt.objects.filter(
        company=user.company, created_at__gte=start
    )
    events = AIEvent.objects.filter(company=user.company, created_at__gte=start)
    provider_interactions = interactions.exclude(provider="local")
    local_interactions = interactions.filter(provider="local")
    totals = interactions.aggregate(interactions=Count("id"))
    provider_totals = provider_interactions.aggregate(
        interactions=Count("id"),
        total_tokens=Sum("total_tokens"),
        cost=Sum("estimated_cost_usd"),
        latency=Sum("latency_ms"),
    )
    interaction_count = totals["interactions"] or 0
    provider_request_count = provider_totals["interactions"] or 0
    action_counts = {
        row["status"]: row["total"]
        for row in actions.values("status").annotate(total=Count("id"))
    }
    event_counts = {
        row["event_type"]: row["total"]
        for row in events.values("event_type").annotate(total=Count("id"))
    }
    capability_rows = list(
        actions.values("tool_name")
        .annotate(
            prepared=Count("id"),
            completed=Count("id", filter=Q(status=AIActionAttempt.Status.COMPLETED)),
            canceled=Count("id", filter=Q(status=AIActionAttempt.Status.CANCELED)),
            failed=Count("id", filter=Q(status=AIActionAttempt.Status.FAILED)),
        )
        .order_by("-prepared", "tool_name")
    )
    monthly = current_month_usage(user.company)
    cost_limit = effective_cost_limit(policy)
    request_limit = policy.monthly_request_limit
    cost_percent = (
        min(float(monthly["cost"] / cost_limit * 100), 100.0) if cost_limit else 100.0
    )
    request_percent = min(monthly["requests"] / request_limit * 100, 100.0)
    return {
        "days": days,
        "monthly_requests": monthly["requests"],
        "monthly_request_limit": request_limit,
        "monthly_request_percent": round(request_percent, 1),
        "monthly_cost": monthly["cost"],
        "monthly_cost_limit": cost_limit,
        "monthly_cost_percent": round(cost_percent, 1),
        "interaction_count": interaction_count,
        "provider_request_count": provider_request_count,
        "local_action_count": local_interactions.count(),
        "completed_interactions": interactions.filter(
            status=AIInteraction.Status.COMPLETED
        ).count(),
        "blocked_interactions": (
            interactions.filter(status=AIInteraction.Status.BLOCKED).count()
            + interactions.filter(
                status=AIInteraction.Status.FAILED,
                error_code="domain_validation",
            ).count()
        ),
        "failed_interactions": (
            interactions.filter(status=AIInteraction.Status.FAILED)
            .exclude(error_code="domain_validation")
            .count()
        ),
        "total_tokens": provider_totals["total_tokens"] or 0,
        "estimated_cost": provider_totals["cost"] or 0,
        "average_latency_ms": round(
            (provider_totals["latency"] or 0) / provider_request_count
        )
        if provider_request_count
        else 0,
        "action_counts": action_counts,
        "event_counts": event_counts,
        "action_outcomes": [
            {"label": label, "value": action_counts.get(value, 0)}
            for value, label in AIActionAttempt.Status.choices
        ],
        "event_outcomes": [
            {"label": label, "value": event_counts.get(value, 0)}
            for value, label in AIEvent.Type.choices
        ],
        "capabilities": capability_rows,
    }


def draft_quality_metrics(user, days=90):
    """Company-scoped, metadata-only adoption and revision metrics."""
    start = timezone.now() - timedelta(days=days)
    reviews = list(
        AIDocumentDraftReview.objects.filter(
            company=user.company,
            created_at__gte=start,
        )
        .select_related("document", "action_attempt")
        .order_by("-created_at", "-pk")
    )
    outcome_counts = {
        value: 0 for value, _label in AIDocumentDraftReview.Outcome.choices
    }
    type_counts = {}
    field_counts = {}
    issue_seconds = []
    total_revisions = 0
    for review in reviews:
        outcome_counts[review.outcome] = outcome_counts.get(review.outcome, 0) + 1
        type_counts[review.document_type] = type_counts.get(review.document_type, 0) + 1
        total_revisions += review.revision_count
        for field in review.changed_fields or []:
            field_counts[field] = field_counts.get(field, 0) + 1
        if review.issued_at:
            issue_seconds.append(
                max((review.issued_at - review.created_at).total_seconds(), 0)
            )

    adopted = outcome_counts.get(
        AIDocumentDraftReview.Outcome.USED_AS_IS, 0
    ) + outcome_counts.get(AIDocumentDraftReview.Outcome.EDITED_THEN_USED, 0)
    finalized = adopted + outcome_counts.get(AIDocumentDraftReview.Outcome.ABANDONED, 0)
    as_is = outcome_counts.get(AIDocumentDraftReview.Outcome.USED_AS_IS, 0)
    stale_cutoff = timezone.now() - timedelta(
        days=getattr(settings, "AI_DRAFT_STALE_DAYS", 14)
    )
    stale = sum(
        1
        for review in reviews
        if review.outcome == AIDocumentDraftReview.Outcome.ACTIVE
        and review.created_at < stale_cutoff
    )
    return {
        "days": days,
        "total": len(reviews),
        "active": outcome_counts.get(AIDocumentDraftReview.Outcome.ACTIVE, 0),
        "stale": stale,
        "adopted": adopted,
        "abandoned": outcome_counts.get(AIDocumentDraftReview.Outcome.ABANDONED, 0),
        "used_as_is": as_is,
        "edited_then_used": outcome_counts.get(
            AIDocumentDraftReview.Outcome.EDITED_THEN_USED, 0
        ),
        "adoption_percent": round(adopted / finalized * 100, 1) if finalized else 0,
        "as_is_percent": round(as_is / adopted * 100, 1) if adopted else 0,
        "average_revisions": round(total_revisions / len(reviews), 1) if reviews else 0,
        "average_minutes_to_issue": round(
            sum(issue_seconds) / len(issue_seconds) / 60, 1
        )
        if issue_seconds
        else 0,
        "outcomes": [
            {
                "value": value,
                "label": label,
                "count": outcome_counts.get(value, 0),
            }
            for value, label in AIDocumentDraftReview.Outcome.choices
        ],
        "types": [
            {"type": key, "label": key.replace("_", " ").title(), "count": value}
            for key, value in sorted(type_counts.items())
        ],
        "changed_fields": [
            {"field": key, "label": key.replace("_", " ").title(), "count": value}
            for key, value in sorted(
                field_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "recent": reviews[:50],
    }
