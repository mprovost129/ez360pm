from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from core.mixins import CompanyScopedQuerysetMixin

from .forms import (
    InvoiceCreateForm,
    InvoiceEditForm,
    InvoiceFilterForm,
    LineItemForm,
    PaymentForm,
    TimeAttachmentForm,
    VoidInvoiceForm,
)
from .models import Document, InvoiceCredit, LineItem, Payment
from .pdf import build_invoice_pdf
from .proposal_forms import InvoiceCreditForm
from .proposal_services import remove_retainer_credit
from .reporting import outstanding_invoices
from .services import (
    attach_time_to_invoice,
    delete_draft_document,
    delete_line_item,
    delete_payment,
    issue_document,
    record_public_view,
    release_void_invoice_time,
    void_invoice,
)


def scoped_invoice(request, pk, *, draft=False):
    queryset = Document.objects.for_company(request.user.company).filter(
        doc_type=Document.Type.INVOICE
    )
    if draft:
        queryset = queryset.filter(status=Document.Status.DRAFT)
    return get_object_or_404(queryset.select_related("project", "project__client"), pk=pk)


class InvoiceListView(LoginRequiredMixin, CompanyScopedQuerysetMixin, ListView):
    model = Document
    context_object_name = "invoices"
    template_name = "documents/invoice_list.html"
    paginate_by = 50
    filter_form = None

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .filter(doc_type=Document.Type.INVOICE)
            .select_related("project", "project__client")
            .prefetch_related("project__client__contacts", "payments")
        )
        self.filter_form = InvoiceFilterForm(
            self.request.GET or None,
            company=self.request.user.company,
        )
        if self.filter_form.is_valid():
            for field in ("status", "invoice_kind", "project"):
                value = self.filter_form.cleaned_data.get(field)
                if value:
                    queryset = queryset.filter(**{field: value})
            client = self.filter_form.cleaned_data.get("client")
            if client:
                queryset = queryset.filter(project__client=client)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        return context


class OutstandingInvoiceListView(LoginRequiredMixin, ListView):
    model = Document
    context_object_name = "invoices"
    template_name = "documents/outstanding_invoice_list.html"
    paginate_by = 50

    def get_queryset(self):
        queryset = outstanding_invoices(self.request.user.company)
        if self.request.GET.get("overdue") == "1":
            queryset = queryset.filter(due_date__lt=timezone.localdate())
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["outstanding_total"] = sum(
            (invoice.balance_amount for invoice in self.object_list),
            Decimal("0.00"),
        )
        context["overdue_only"] = self.request.GET.get("overdue") == "1"
        context["today"] = timezone.localdate()
        return context


class InvoiceDetailView(LoginRequiredMixin, CompanyScopedQuerysetMixin, DetailView):
    model = Document
    context_object_name = "invoice"
    template_name = "documents/invoice_detail.html"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(doc_type=Document.Type.INVOICE)
            .select_related("project", "project__client", "company")
            .prefetch_related(
                "project__client__contacts",
                "line_items__time_entries",
                "payments",
                "credits_received__source_invoice",
                "deliveries",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object.status == Document.Status.DRAFT:
            form = TimeAttachmentForm(invoice=self.object)
            if form.fields["entries"].queryset.exists():
                context["time_attachment_form"] = form
            if self.object.invoice_kind == Document.InvoiceKind.FINAL:
                credit_form = InvoiceCreditForm(destination_invoice=self.object)
                if credit_form.fields["source_invoice"].queryset.exists():
                    context["credit_form"] = credit_form
        return context


class InvoiceCreateView(LoginRequiredMixin, CreateView):
    model = Document
    form_class = InvoiceCreateForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "New invoice", "submit_label": "Create invoice"}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.request.user.company
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        if self.request.GET.get("project"):
            initial["project"] = self.request.GET["project"]
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Invoice {self.object.number} created.")
        return response

    def get_success_url(self):
        return reverse("documents:invoice-detail", args=(self.object.pk,))


class InvoiceUpdateView(
    LoginRequiredMixin,
    CompanyScopedQuerysetMixin,
    UpdateView,
):
    model = Document
    form_class = InvoiceEditForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "Edit invoice", "submit_label": "Save invoice"}

    def get_queryset(self):
        return super().get_queryset().filter(
            doc_type=Document.Type.INVOICE,
            status=Document.Status.DRAFT,
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.request.user.company
        return kwargs

    def get_success_url(self):
        return reverse("documents:invoice-detail", args=(self.object.pk,))


class InvoiceDeleteView(LoginRequiredMixin, View):
    template_name = "shared/confirm_delete.html"

    def get(self, request, pk):
        from django.shortcuts import render

        invoice = scoped_invoice(request, pk, draft=True)
        return render(
            request,
            self.template_name,
            {
                "object": invoice,
                "page_title": "Delete draft invoice",
                "warning": "Attached time will return to the unbilled pool.",
            },
        )

    def post(self, request, pk):
        invoice = scoped_invoice(request, pk, draft=True)
        delete_draft_document(document=invoice)
        messages.success(request, "Draft invoice deleted and attached time released.")
        return redirect("documents:invoice-list")


class InvoiceChildFormMixin(LoginRequiredMixin):
    invoice = None

    def dispatch(self, request, *args, **kwargs):
        self.invoice = scoped_invoice(request, kwargs["invoice_pk"], draft=True)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["document"] = self.invoice
        return kwargs

    def get_success_url(self):
        return reverse("documents:invoice-detail", args=(self.invoice.pk,))


class LineItemCreateView(InvoiceChildFormMixin, CreateView):
    model = LineItem
    form_class = LineItemForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "Add invoice line", "submit_label": "Add line"}


class LineItemUpdateView(InvoiceChildFormMixin, UpdateView):
    model = LineItem
    form_class = LineItemForm
    template_name = "shared/form.html"
    pk_url_kwarg = "line_pk"
    extra_context = {"page_title": "Edit invoice line", "submit_label": "Save line"}

    def get_queryset(self):
        return self.invoice.line_items.all()


class LineItemDeleteView(LoginRequiredMixin, View):
    def post(self, request, invoice_pk, line_pk):
        invoice = scoped_invoice(request, invoice_pk, draft=True)
        line = get_object_or_404(invoice.line_items, pk=line_pk)
        delete_line_item(line=line)
        messages.success(request, "Line removed and attached time released.")
        return redirect("documents:invoice-detail", pk=invoice.pk)


class AttachTimeView(LoginRequiredMixin, FormView):
    form_class = TimeAttachmentForm
    invoice = None

    def dispatch(self, request, *args, **kwargs):
        self.invoice = scoped_invoice(request, kwargs["pk"], draft=True)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["invoice"] = self.invoice
        return kwargs

    def form_valid(self, form):
        try:
            attach_time_to_invoice(
                invoice=self.invoice,
                entries=form.cleaned_data["entries"],
                grouping=form.cleaned_data["grouping"],
            )
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)
        messages.success(self.request, "Time added to invoice.")
        return redirect("documents:invoice-detail", pk=self.invoice.pk)

    def form_invalid(self, form):
        messages.error(self.request, "Select valid uninvoiced time entries.")
        return redirect("documents:invoice-detail", pk=self.invoice.pk)


@login_required
@require_POST
def invoice_issue(request, pk):
    invoice = scoped_invoice(request, pk, draft=True)
    try:
        issue_document(document=invoice)
    except ValidationError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, "Invoice issued. Its public link is now active.")
    return redirect("documents:invoice-detail", pk=invoice.pk)


class InvoiceVoidView(LoginRequiredMixin, FormView):
    form_class = VoidInvoiceForm
    template_name = "documents/invoice_void.html"
    invoice = None

    def dispatch(self, request, *args, **kwargs):
        self.invoice = scoped_invoice(request, kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["invoice"] = self.invoice
        return context

    def form_valid(self, form):
        try:
            void_invoice(invoice=self.invoice, reason=form.cleaned_data["reason"])
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)
        messages.success(self.request, "Invoice voided. Attached time remains invoiced.")
        return redirect("documents:invoice-detail", pk=self.invoice.pk)


class ReleaseVoidTimeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        invoice = scoped_invoice(request, pk)
        try:
            count = release_void_invoice_time(invoice=invoice)
        except ValidationError as exc:
            messages.error(request, exc.message)
        else:
            messages.warning(request, f"Released {count} time entries for rebilling.")
        return redirect("documents:invoice-detail", pk=invoice.pk)


class PaymentViewMixin(LoginRequiredMixin):
    invoice = None

    def dispatch(self, request, *args, **kwargs):
        self.invoice = scoped_invoice(request, kwargs["invoice_pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["invoice"] = self.invoice
        return kwargs

    def get_success_url(self):
        return reverse("documents:invoice-detail", args=(self.invoice.pk,))


class PaymentCreateView(PaymentViewMixin, CreateView):
    model = Payment
    form_class = PaymentForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "Record payment", "submit_label": "Record payment"}


class PaymentUpdateView(PaymentViewMixin, UpdateView):
    model = Payment
    form_class = PaymentForm
    template_name = "shared/form.html"
    pk_url_kwarg = "payment_pk"
    extra_context = {"page_title": "Edit payment", "submit_label": "Save payment"}

    def get_queryset(self):
        return self.invoice.payments.exclude(method=Payment.Method.STRIPE)


class PaymentDeleteView(LoginRequiredMixin, View):
    def post(self, request, invoice_pk, payment_pk):
        invoice = scoped_invoice(request, invoice_pk)
        payment = get_object_or_404(
            invoice.payments.exclude(method=Payment.Method.STRIPE),
            pk=payment_pk,
        )
        delete_payment(payment=payment)
        messages.success(request, "Payment removed and invoice status recalculated.")
        return redirect("documents:invoice-detail", pk=invoice.pk)


class InvoiceCreditCreateView(LoginRequiredMixin, FormView):
    form_class = InvoiceCreditForm
    template_name = "shared/form.html"
    invoice = None
    extra_context = {"page_title": "Apply retainer credit", "submit_label": "Apply credit"}

    def dispatch(self, request, *args, **kwargs):
        self.invoice = scoped_invoice(request, kwargs["invoice_pk"], draft=True)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["destination_invoice"] = self.invoice
        return kwargs

    def form_valid(self, form):
        try:
            form.save()
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
            return self.form_invalid(form)
        messages.success(self.request, "Retainer credit applied.")
        return redirect("documents:invoice-detail", pk=self.invoice.pk)


class InvoiceCreditDeleteView(LoginRequiredMixin, View):
    def post(self, request, invoice_pk, credit_pk):
        invoice = scoped_invoice(request, invoice_pk, draft=True)
        credit = get_object_or_404(
            InvoiceCredit.objects.filter(destination_invoice=invoice),
            pk=credit_pk,
        )
        try:
            remove_retainer_credit(credit=credit)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, "Retainer credit removed.")
        return redirect("documents:invoice-detail", pk=invoice.pk)


class InvoicePdfView(LoginRequiredMixin, View):
    def get(self, request, pk):
        invoice = scoped_invoice(request, pk)
        response = HttpResponse(build_invoice_pdf(invoice), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{invoice.number}.pdf"'
        return response


class PublicInvoiceView(DetailView):
    model = Document
    context_object_name = "invoice"
    template_name = "documents/public_invoice.html"
    slug_field = "public_token"
    slug_url_kwarg = "token"

    def get_queryset(self):
        return Document.objects.filter(doc_type=Document.Type.INVOICE).exclude(
            status=Document.Status.DRAFT
        ).select_related("company", "project", "project__client").prefetch_related(
            "project__client__contacts",
            "line_items",
            "payments",
        )

    def get_object(self, queryset=None):
        invoice = super().get_object(queryset)
        return record_public_view(document=invoice)


class PublicInvoicePdfView(View):
    def get(self, request, token):
        invoice = get_object_or_404(
            Document.objects.filter(doc_type=Document.Type.INVOICE).exclude(
                status=Document.Status.DRAFT
            ),
            public_token=token,
        )
        response = HttpResponse(build_invoice_pdf(invoice), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{invoice.number}.pdf"'
        return response
