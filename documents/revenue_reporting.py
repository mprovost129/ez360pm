from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.utils import timezone

from .models import Payment, PaymentAdjustment, PaymentFeeReconciliationAttempt

ZERO = Decimal("0.00")
VALID_PRESETS = {
    "this_month",
    "last_month",
    "this_year",
    "last_year",
    "year",
    "custom",
}


@dataclass(frozen=True)
class RevenueFilters:
    start_date: date
    end_date: date
    preset: str
    method: str = ""
    calendar_year: int | None = None
    pending_fees_only: bool = False

    @staticmethod
    def _format_day(value, *, abbreviated=False):
        month = value.strftime("%b" if abbreviated else "%B")
        return f"{month} {value.day}, {value.year}"

    @property
    def period_label(self):
        if self.start_date == self.end_date:
            return self._format_day(self.start_date)
        if self.start_date == date(self.start_date.year, 1, 1) and self.end_date == date(
            self.start_date.year, 12, 31
        ):
            return str(self.start_date.year)
        if (
            self.start_date.day == 1
            and self.end_date.year == self.start_date.year
            and self.end_date.month == self.start_date.month
        ):
            return self.start_date.strftime("%B %Y")
        return (
            f"{self._format_day(self.start_date, abbreviated=True)}–"
            f"{self._format_day(self.end_date, abbreviated=True)}"
        )

    @property
    def query_params(self):
        values = {
            "preset": self.preset,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
        }
        if self.method:
            values["method"] = self.method
        if self.calendar_year:
            values["year"] = str(self.calendar_year)
        if self.pending_fees_only:
            values["fee_status"] = "pending"
        return values

    @property
    def query_string(self):
        return urlencode(self.query_params)


def _month_bounds(day):
    start = day.replace(day=1)
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, next_month - timedelta(days=1)


def _safe_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _safe_year(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    if 1900 <= year <= 2200:
        return year
    return None


def parse_revenue_filters(params, *, today=None):
    today = today or timezone.localdate()
    preset = params.get("preset") or ""

    # Backward compatibility with the original month-only report links.
    old_month = params.get("month")
    if old_month and not preset:
        parsed_month = _safe_date(f"{old_month}-01")
        if parsed_month:
            start_date, end_date = _month_bounds(parsed_month)
            method = params.get("method", "")
            if method not in Payment.Method.values:
                method = ""
            return RevenueFilters(
                start_date,
                end_date,
                "custom",
                method,
                pending_fees_only=params.get("fee_status") == "pending",
            )

    if preset not in VALID_PRESETS:
        preset = "this_month"

    calendar_year = _safe_year(params.get("year"))
    if preset == "last_month":
        this_month, _ = _month_bounds(today)
        start_date, end_date = _month_bounds(this_month - timedelta(days=1))
    elif preset == "this_year":
        start_date, end_date = date(today.year, 1, 1), date(today.year, 12, 31)
    elif preset == "last_year":
        start_date, end_date = date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    elif preset == "year":
        year = calendar_year or today.year
        start_date, end_date = date(year, 1, 1), date(year, 12, 31)
        calendar_year = year
    elif preset == "custom":
        start_date = _safe_date(params.get("start_date"))
        end_date = _safe_date(params.get("end_date"))
        if not start_date or not end_date or end_date < start_date:
            preset = "this_month"
            start_date, end_date = _month_bounds(today)
    else:
        start_date, end_date = _month_bounds(today)

    method = params.get("method", "")
    if method not in Payment.Method.values:
        method = ""

    return RevenueFilters(
        start_date=start_date,
        end_date=end_date,
        preset=preset,
        method=method,
        calendar_year=calendar_year,
        pending_fees_only=params.get("fee_status") == "pending",
    )


@dataclass(frozen=True)
class RevenueLedgerEntry:
    effective_date: date
    created_at: object
    entry_type: str
    payment: Payment
    reference: str
    gross: Decimal = ZERO
    fee: Decimal = ZERO
    fee_adjustment: Decimal = ZERO
    adjustment: Decimal = ZERO
    fee_pending: bool = False
    provider_reference: str = ""
    record_id: str = ""
    fee_attempted_at: object = None
    fee_attempt_status: str = ""
    fee_attempt_message: str = ""

    @property
    def fee_effect(self):
        """Signed fee cost for this row; negative values are provider credits."""
        return self.fee - self.fee_adjustment

    @property
    def net(self):
        return self.gross - self.fee_effect + self.adjustment

    @property
    def invoice(self):
        return self.payment.document

    @property
    def project(self):
        return self.payment.document.project

    @property
    def client(self):
        return self.payment.document.project.client

    @property
    def method(self):
        return self.payment.method

    @property
    def method_label(self):
        return self.payment.get_method_display()

    @property
    def invoice_kind_label(self):
        return self.payment.document.get_invoice_kind_display()

    @property
    def provider_id(self):
        return self.provider_reference


@dataclass
class RevenueReport:
    filters: RevenueFilters
    entries: list[RevenueLedgerEntry]
    gross: Decimal
    fees: Decimal
    original_fees: Decimal
    fee_adjustments: Decimal
    adjustments: Decimal
    net: Decimal
    payment_count: int
    adjustment_count: int
    pending_fee_count: int
    method_rows: list[dict]

    @property
    def transaction_count(self):
        return self.payment_count + self.adjustment_count

    @property
    def is_final(self):
        return self.pending_fee_count == 0

    def page(self, page_number, *, per_page=100):
        return Paginator(self.entries, per_page).get_page(page_number)


def _base_payments(company, filters):
    queryset = Payment.objects.filter(
        document__company=company,
        received_at__range=(filters.start_date, filters.end_date),
    )
    if filters.method:
        queryset = queryset.filter(method=filters.method)
    if filters.pending_fees_only:
        queryset = queryset.filter(method=Payment.Method.STRIPE, fee_pending=True)
    return queryset.select_related(
        "document",
        "document__project",
        "document__project__client",
    ).prefetch_related("document__project__client__contacts")


def _base_adjustments(company, filters):
    if filters.pending_fees_only:
        return PaymentAdjustment.objects.none()
    queryset = PaymentAdjustment.objects.filter(
        company=company,
        effective_at__range=(filters.start_date, filters.end_date),
    )
    if filters.method:
        queryset = queryset.filter(payment__method=filters.method)
    return queryset.select_related(
        "payment",
        "payment__document",
        "payment__document__project",
        "payment__document__project__client",
    ).prefetch_related("payment__document__project__client__contacts")


def build_revenue_report(*, company, filters):
    payments = list(_base_payments(company, filters))
    adjustments = list(_base_adjustments(company, filters))

    latest_attempts = {}
    if payments:
        attempts = PaymentFeeReconciliationAttempt.objects.filter(
            company=company,
            payment_id__in=[payment.pk for payment in payments],
        ).order_by("payment_id", "-attempted_at", "-pk")
        for attempt in attempts:
            latest_attempts.setdefault(attempt.payment_id, attempt)

    entries = [
        RevenueLedgerEntry(
            effective_date=payment.received_at,
            created_at=payment.created_at,
            entry_type="payment",
            payment=payment,
            reference=payment.reference,
            gross=payment.amount,
            fee=payment.fee_amount,
            fee_pending=payment.fee_pending,
            provider_reference=payment.stripe_payment_intent_id or "",
            record_id=f"payment:{payment.pk}",
            fee_attempted_at=(
                latest_attempts[payment.pk].attempted_at
                if payment.pk in latest_attempts
                else None
            ),
            fee_attempt_status=(
                latest_attempts[payment.pk].get_status_display()
                if payment.pk in latest_attempts
                else ""
            ),
            fee_attempt_message=(
                latest_attempts[payment.pk].error_message
                if payment.pk in latest_attempts
                else ""
            ),
        )
        for payment in payments
    ]
    entries.extend(
        RevenueLedgerEntry(
            effective_date=adjustment.effective_at,
            created_at=adjustment.created_at,
            entry_type="adjustment",
            payment=adjustment.payment,
            reference=adjustment.reference or adjustment.get_adjustment_type_display(),
            fee_adjustment=(
                adjustment.amount if adjustment.affects_processing_fees else ZERO
            ),
            adjustment=(
                ZERO if adjustment.affects_processing_fees else adjustment.amount
            ),
            provider_reference=adjustment.provider_id,
            record_id=f"adjustment:{adjustment.pk}",
        )
        for adjustment in adjustments
    )
    entries.sort(
        key=lambda entry: (
            entry.effective_date,
            entry.created_at,
            entry.record_id,
        ),
        reverse=True,
    )

    gross = sum((payment.amount for payment in payments), ZERO)
    original_fees = sum((payment.fee_amount for payment in payments), ZERO)
    fee_adjustment_total = sum(
        (
            adjustment.amount
            for adjustment in adjustments
            if adjustment.affects_processing_fees
        ),
        ZERO,
    )
    fees = original_fees - fee_adjustment_total
    adjustment_total = sum(
        (
            adjustment.amount
            for adjustment in adjustments
            if not adjustment.affects_processing_fees
        ),
        ZERO,
    )

    method_rows = []
    for method, label in Payment.Method.choices:
        method_payments = [payment for payment in payments if payment.method == method]
        method_adjustments = [
            adjustment for adjustment in adjustments if adjustment.payment.method == method
        ]
        method_gross = sum((payment.amount for payment in method_payments), ZERO)
        method_original_fees = sum(
            (payment.fee_amount for payment in method_payments), ZERO
        )
        method_fee_adjustments = sum(
            (
                adjustment.amount
                for adjustment in method_adjustments
                if adjustment.affects_processing_fees
            ),
            ZERO,
        )
        method_fees = method_original_fees - method_fee_adjustments
        method_adjustment_total = sum(
            (
                adjustment.amount
                for adjustment in method_adjustments
                if not adjustment.affects_processing_fees
            ),
            ZERO,
        )
        method_rows.append(
            {
                "method": method,
                "label": label,
                "count": len(method_payments) + len(method_adjustments),
                "payment_count": len(method_payments),
                "gross": method_gross,
                "fees": method_fees,
                "original_fees": method_original_fees,
                "fee_adjustments": method_fee_adjustments,
                "adjustments": method_adjustment_total,
                "net": method_gross - method_fees + method_adjustment_total,
                "pending_fee_count": sum(
                    1 for payment in method_payments if payment.fee_pending
                ),
            }
        )

    return RevenueReport(
        filters=filters,
        entries=entries,
        gross=gross,
        fees=fees,
        original_fees=original_fees,
        fee_adjustments=fee_adjustment_total,
        adjustments=adjustment_total,
        net=gross - fees + adjustment_total,
        payment_count=len(payments),
        adjustment_count=len(adjustments),
        pending_fee_count=sum(1 for payment in payments if payment.fee_pending),
        method_rows=method_rows,
    )


def available_revenue_years(*, company, today=None):
    today = today or timezone.localdate()
    payment_dates = Payment.objects.filter(document__company=company).values_list(
        "received_at", flat=True
    )
    adjustment_dates = PaymentAdjustment.objects.filter(company=company).values_list(
        "effective_at", flat=True
    )
    years = {today.year}
    years.update(value.year for value in payment_dates)
    years.update(value.year for value in adjustment_dates)
    return sorted(years, reverse=True)
