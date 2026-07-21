from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DurationField, ExpressionWrapper, F, Q, Sum
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
        F("time_entries__end_time") - F("time_entries__start_time"),
        output_field=DurationField(),
    )
    leads = (
        Project.objects.for_company(company)
        .filter(status=Project.Status.LEAD)
        .select_related("client")
        .prefetch_related("client__contacts", "documents")
    )
    approved = (
        Project.objects.for_company(company)
        .filter(status=Project.Status.APPROVED)
        .select_related("client")
        .prefetch_related("client__contacts", "documents")
    )
    active = (
        Project.objects.for_company(company)
        .filter(status=Project.Status.ACTIVE)
        .select_related("client")
        .annotate(
            unbilled_entry_count=Count("time_entries", filter=unbilled_filter),
            unbilled_duration=Sum(duration_expression, filter=unbilled_filter),
        )
    )
    drafts = (
        Document.objects.for_company(company)
        .filter(status=Document.Status.DRAFT)
        .select_related("project", "project__client")
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
        duration=Sum(
            ExpressionWrapper(
                F("end_time") - F("start_time"),
                output_field=DurationField(),
            )
        ),
    )
    unbilled_duration = unbilled["duration"] or timedelta()
    return {
        "recent_notes": Note.objects.for_company(company).filter(is_archived=False)[:5],
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
        "month_revenue": revenue,
        "revenue_month": month_start,
        "dashboard_today": today,
    }
