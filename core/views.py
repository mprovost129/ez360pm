import csv

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, TemplateView

from documents.models import Document, Payment
from documents.revenue_reporting import (
    available_revenue_years,
    build_revenue_report,
    parse_revenue_filters,
)
from documents.stripe_services import reconcile_pending_payment_fee

from .dashboard import dashboard_context


class HomeView(LoginRequiredMixin, TemplateView):
    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(dashboard_context(self.request.user.company))
        return context


def _spreadsheet_safe(value):
    text = str(value or "")
    if text.startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


class RevenueView(LoginRequiredMixin, TemplateView):
    template_name = "core/revenue.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filters = parse_revenue_filters(self.request.GET)
        report = build_revenue_report(
            company=self.request.user.company,
            filters=filters,
        )
        is_print = self.request.GET.get("print") == "1"
        per_page = max(len(report.entries), 1) if is_print else 100
        page_obj = report.page(self.request.GET.get("page"), per_page=per_page)
        available_years = available_revenue_years(company=self.request.user.company)
        if filters.calendar_year and filters.calendar_year not in available_years:
            available_years.append(filters.calendar_year)
            available_years.sort(reverse=True)
        context.update(
            {
                "report": report,
                "filters": filters,
                "entries": page_obj.object_list,
                "page_obj": page_obj,
                "paginator": page_obj.paginator,
                "is_paginated": page_obj.has_other_pages(),
                "method_choices": Payment.Method.choices,
                "available_years": available_years,
                "export_query": filters.query_string,
                "print_query": f"{filters.query_string}&print=1",
                "is_print": is_print,
                "books_closed_through": self.request.user.company.books_closed_through,
                # Backward-compatible names used by existing tests and any
                # saved template customizations.
                "revenue_total": report.gross,
                "fee_total": report.fees,
                "net_total": report.net,
                "pending_fee_count": report.pending_fee_count,
                "method_totals": report.method_rows,
            }
        )
        return context


class RevenueCsvView(LoginRequiredMixin, View):
    def get(self, request):
        filters = parse_revenue_filters(request.GET)
        report = build_revenue_report(company=request.user.company, filters=filters)
        fee_suffix = "-pending-fees" if filters.pending_fees_only else ""
        filename = (
            f"ez360pm-payments-{filters.start_date.isoformat()}-to-"
            f"{filters.end_date.isoformat()}-{filters.method or 'all'}{fee_suffix}.csv"
        )
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(["EZ360PM Revenue & Fees Report"])
        writer.writerow(["Company", _spreadsheet_safe(request.user.company.name)])
        writer.writerow(["Generated at", timezone.localtime().isoformat()])
        writer.writerow(["Period", filters.period_label])
        writer.writerow(["Method", Payment.Method(filters.method).label if filters.method else "All methods"])
        writer.writerow(["Fee status", "Pending only" if filters.pending_fees_only else "All fee statuses"])
        writer.writerow(["Financial records locked through", request.user.company.books_closed_through or "Not locked"])
        writer.writerow(["Gross received", f"{report.gross:.2f}"])
        writer.writerow(["Original processing fees", f"{report.original_fees:.2f}"])
        writer.writerow(["Processing fee adjustments", f"{report.fee_adjustments:.2f}"])
        writer.writerow(["Net processing fees", f"{report.fees:.2f}"])
        writer.writerow(["Refunds / other adjustments", f"{report.adjustments:.2f}"])
        writer.writerow(["Net after known fees", f"{report.net:.2f}"])
        writer.writerow(["Pending Stripe fees", report.pending_fee_count])
        writer.writerow([])
        writer.writerow(
            [
                "Effective date",
                "Entry type",
                "Client",
                "Project",
                "Invoice",
                "Invoice kind",
                "Method",
                "Reference",
                "Gross",
                "Original fee",
                "Fee adjustment",
                "Fee status",
                "Last fee reconciliation attempt",
                "Fee reconciliation result",
                "Fee reconciliation detail",
                "Refund / other adjustment",
                "Net",
                "Stripe Payment Intent ID",
                "Provider adjustment ID",
                "Internal record ID",
            ]
        )
        for entry in report.entries:
            writer.writerow(
                [
                    entry.effective_date.isoformat(),
                    entry.entry_type.title(),
                    _spreadsheet_safe(entry.client.display_name),
                    _spreadsheet_safe(entry.project.name),
                    _spreadsheet_safe(entry.invoice.number),
                    entry.invoice_kind_label,
                    entry.method_label,
                    _spreadsheet_safe(entry.reference),
                    f"{entry.gross:.2f}",
                    "" if entry.fee_pending else f"{entry.fee:.2f}",
                    f"{entry.fee_adjustment:.2f}",
                    (
                        "Pending"
                        if entry.fee_pending
                        else ("Confirmed" if entry.entry_type == "payment" else "")
                    ),
                    (
                        timezone.localtime(entry.fee_attempted_at).isoformat()
                        if entry.fee_attempted_at
                        else ""
                    ),
                    entry.fee_attempt_status,
                    _spreadsheet_safe(entry.fee_attempt_message),
                    f"{entry.adjustment:.2f}",
                    "" if entry.fee_pending else f"{entry.net:.2f}",
                    _spreadsheet_safe(entry.payment.stripe_payment_intent_id),
                    _spreadsheet_safe(
                        entry.provider_id if entry.entry_type == "adjustment" else ""
                    ),
                    entry.record_id,
                ]
            )
        return response


class RevenueFeeReconcileView(LoginRequiredMixin, View):
    def post(self, request):
        filters = parse_revenue_filters(request.POST)
        pending = Payment.objects.filter(
            document__company=request.user.company,
            method=Payment.Method.STRIPE,
            fee_pending=True,
            received_at__range=(filters.start_date, filters.end_date),
        )
        if filters.method and filters.method != Payment.Method.STRIPE:
            pending = pending.none()
        reconciled = 0
        still_pending = 0
        for payment in pending:
            if reconcile_pending_payment_fee(payment=payment):
                reconciled += 1
            else:
                still_pending += 1
        if reconciled:
            messages.success(
                request,
                f"Reconciled {reconciled} Stripe fee{'' if reconciled == 1 else 's'}.",
            )
        if still_pending:
            messages.warning(
                request,
                f"{still_pending} Stripe fee{'' if still_pending == 1 else 's'} "
                "are still unavailable from Stripe.",
            )
        return redirect(f"{reverse('core:revenue')}?{filters.query_string}")


class DraftDocumentListView(LoginRequiredMixin, ListView):
    model = Document
    context_object_name = "documents"
    template_name = "core/draft_documents.html"
    paginate_by = 50

    def get_queryset(self):
        return Document.objects.for_company(self.request.user.company).filter(
            status=Document.Status.DRAFT
        ).select_related("project", "project__client")


class HealthView(View):
    """Minimal deployment health check including database connectivity."""

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception:
            return JsonResponse({"status": "unavailable"}, status=503)
        return JsonResponse({"status": "ok"})
