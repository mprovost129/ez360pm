from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DurationField, ExpressionWrapper, F, Min, Q, Sum
from django.utils import timezone

from documents.models import Document, Payment
from documents.reporting import outstanding_invoices
from intake.models import Note
from projects.models import Project, TimeEntry


def dashboard_context(company):
    unbilled_filter = Q(
        time_entries__end_time__isnull=False,
        time_entries__billable=True,
        time_entries__status=TimeEntry.Status.LOGGED,
        time_entries__line_item__isnull=True,
    )
    duration_expression = ExpressionWrapper(
        F("time_entries__end_time")
        - F("time_entries__start_time")
        - F("time_entries__paused_duration"),
        output_field=DurationField(),
    )
    leads = (
        Project.objects.for_company(company)
        .filter(status=Project.Status.LEAD)
        .select_related("client")
        .prefetch_related("client__contacts", "documents")
        .order_by("created_at", "pk")
    )
    approved = (
        Project.objects.for_company(company)
        .filter(status=Project.Status.APPROVED)
        .select_related("client")
        .prefetch_related("client__contacts", "documents")
        .order_by("updated_at", "pk")
    )
    active = (
        Project.objects.for_company(company)
        .filter(status=Project.Status.ACTIVE)
        .select_related("client")
        .annotate(
            unbilled_entry_count=Count("time_entries", filter=unbilled_filter),
            unbilled_duration=Sum(duration_expression, filter=unbilled_filter),
            oldest_unbilled_at=Min("time_entries__start_time", filter=unbilled_filter),
        )
        .order_by(F("oldest_unbilled_at").asc(nulls_last=True), "pk")
    )
    drafts = (
        Document.objects.for_company(company)
        .filter(status=Document.Status.DRAFT)
        .select_related("project", "project__client")
        .order_by("created_at", "pk")
    )
    unpaid = outstanding_invoices(company).prefetch_related("payments")
    today = timezone.localdate()
    month_start = today.replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    revenue = (
        Payment.objects.filter(
            document__company=company,
            received_at__gte=month_start,
            received_at__lt=next_month,
        ).aggregate(value=Sum("amount"))["value"]
        or Decimal("0.00")
    )
    unbilled = TimeEntry.objects.filter(
        company=company,
        end_time__isnull=False,
        billable=True,
        status=TimeEntry.Status.LOGGED,
        line_item__isnull=True,
    ).aggregate(
        count=Count("pk"),
        oldest=Min("start_time"),
        duration=Sum(
            ExpressionWrapper(
                F("end_time") - F("start_time") - F("paused_duration"),
                output_field=DurationField(),
            )
        ),
    )
    unbilled_duration = unbilled["duration"] or timedelta()
    return {
        "recent_notes": Note.objects.for_company(company)
        .filter(is_archived=False)
        .order_by("created_at", "pk")[:5],
        "lead_projects": leads[:8],
        "lead_count": leads.count(),
        "approved_projects": approved[:8],
        "approved_count": approved.count(),
        "active_projects": active[:8],
        "active_count": active.count(),
        "draft_documents": drafts[:8],
        "draft_count": drafts.count(),
        "unpaid_invoices": unpaid[:8],
        "unpaid_count": unpaid.count(),
        "overdue_count": unpaid.filter(due_date__lt=today).count(),
        "unbilled_count": unbilled["count"],
        "unbilled_hours": (
            Decimal(str(unbilled_duration.total_seconds())) / Decimal("3600")
        ).quantize(Decimal("0.01")),
        "oldest_unbilled_at": unbilled["oldest"],
        "month_revenue": revenue,
        "revenue_month": month_start,
        "dashboard_today": today,
    }
