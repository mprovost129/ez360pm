from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from core.mixins import CompanyScopedQuerysetMixin
from documents.models import Document, InvoiceCredit, Payment
from documents.reporting import outstanding_invoices
from intake.models import Note
from projects.models import TimeEntry

from .forms import ClientCreateForm, ClientForm, ContactForm
from .models import Client, Contact
from .services import delete_contact

RECENT_TIME_ENTRY_LIMIT = 25


class CompanyFormMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.request.user.company
        return kwargs


class ClientListView(LoginRequiredMixin, CompanyScopedQuerysetMixin, ListView):
    model = Client
    context_object_name = "clients"
    template_name = "clients/client_list.html"
    paginate_by = 50

    def get_queryset(self):
        return super().get_queryset().ordered_for_list().prefetch_related("contacts")


class ClientDetailView(LoginRequiredMixin, CompanyScopedQuerysetMixin, DetailView):
    model = Client
    context_object_name = "client"
    template_name = "clients/client_detail.html"

    def get_queryset(self):
        return super().get_queryset().prefetch_related("contacts", "projects")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        client = self.object
        company = self.request.user.company

        invoices = (
            Document.objects.for_company(company)
            .filter(doc_type=Document.Type.INVOICE, project__client=client)
            .select_related("project")
            .order_by("-issue_date", "-number")
        )
        proposals = (
            Document.objects.for_company(company)
            .filter(doc_type=Document.Type.PROPOSAL, project__client=client)
            .select_related("project")
            .order_by("-issue_date", "-number")
        )
        time_entries = (
            TimeEntry.objects.filter(company=company, project__client=client)
            .select_related("project", "user")
            .order_by("-start_time")[:RECENT_TIME_ENTRY_LIMIT]
        )
        payments = (
            Payment.objects.filter(document__company=company, document__project__client=client)
            .select_related("document", "document__project")
            .order_by("-received_at", "-created_at")
        )
        credits = (
            InvoiceCredit.objects.filter(
                destination_invoice__company=company,
                destination_invoice__project__client=client,
            )
            .select_related("source_invoice", "destination_invoice")
            .order_by("-created_at")
        )
        notes = (
            Note.objects.for_company(company)
            .filter(client=client, is_archived=False)
            .select_related("project")
            .order_by("-created_at")
        )

        total_invoiced = invoices.exclude(
            status__in=(Document.Status.DRAFT, Document.Status.VOID)
        ).aggregate(value=Sum("total"))["value"] or Decimal("0.00")
        total_received = payments.aggregate(value=Sum("amount"))["value"] or Decimal("0.00")
        outstanding_total = (
            outstanding_invoices(company)
            .filter(project__client=client)
            .aggregate(value=Sum("balance_amount"))["value"]
            or Decimal("0.00")
        )
        durations = TimeEntry.objects.filter(
            company=company,
            project__client=client,
            end_time__isnull=False,
        ).values_list("start_time", "end_time", "paused_duration")
        actual_duration = sum(
            (max(end - start - paused, timedelta()) for start, end, paused in durations),
            timedelta(),
        )
        microseconds = actual_duration // timedelta(microseconds=1)
        actual_hours = (
            Decimal(microseconds) / Decimal("3600000000")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        context.update(
            invoices=invoices,
            proposals=proposals,
            time_entries=time_entries,
            payments=payments,
            credits=credits,
            notes=notes,
            total_invoiced=total_invoiced,
            total_received=total_received,
            outstanding_total=outstanding_total,
            actual_hours=actual_hours,
        )
        return context


class ClientCreateView(LoginRequiredMixin, CompanyFormMixin, CreateView):
    model = Client
    form_class = ClientCreateForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "New client", "submit_label": "Create client"}

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Client created.")
        return response

    def get_success_url(self):
        return reverse("clients:detail", args=(self.object.pk,))


class ClientUpdateView(
    LoginRequiredMixin,
    CompanyScopedQuerysetMixin,
    CompanyFormMixin,
    UpdateView,
):
    model = Client
    form_class = ClientForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "Edit client", "submit_label": "Save client"}

    def get_success_url(self):
        return reverse("clients:detail", args=(self.object.pk,))


class ClientDeleteView(LoginRequiredMixin, CompanyScopedQuerysetMixin, DeleteView):
    model = Client
    template_name = "shared/confirm_delete.html"
    success_url = reverse_lazy("clients:list")
    extra_context = {
        "page_title": "Delete client",
        "warning": "Clients with projects or financial history cannot be deleted.",
    }

    def form_valid(self, form):
        try:
            self.object.delete()
        except ProtectedError:
            messages.error(
                self.request,
                "This client has project history and cannot be deleted.",
            )
            return redirect("clients:detail", pk=self.object.pk)
        messages.success(self.request, "Client deleted.")
        return redirect(self.success_url)


class ContactViewMixin(LoginRequiredMixin):
    client = None

    def dispatch(self, request, *args, **kwargs):
        self.client = get_object_or_404(
            Client.objects.for_company(request.user.company),
            pk=kwargs["client_pk"],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["client"] = self.client
        return kwargs

    def get_success_url(self):
        return reverse("clients:detail", args=(self.client.pk,))


class ContactCreateView(ContactViewMixin, CreateView):
    model = Contact
    form_class = ContactForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "Add contact", "submit_label": "Add contact"}


class ContactUpdateView(ContactViewMixin, UpdateView):
    model = Contact
    form_class = ContactForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "Edit contact", "submit_label": "Save contact"}
    pk_url_kwarg = "contact_pk"

    def get_queryset(self):
        return Contact.objects.filter(client=self.client)


class ContactDeleteView(ContactViewMixin, DeleteView):
    model = Contact
    template_name = "shared/confirm_delete.html"
    pk_url_kwarg = "contact_pk"
    extra_context = {
        "page_title": "Delete contact",
        "warning": "A primary contact cannot be deleted until another contact is primary.",
    }

    def get_queryset(self):
        return Contact.objects.filter(client=self.client)

    def form_valid(self, form):
        try:
            delete_contact(contact=self.object)
        except ValidationError as exc:
            messages.error(self.request, exc.message)
            return redirect(self.get_success_url())
        messages.success(self.request, "Contact deleted.")
        return redirect(self.get_success_url())
