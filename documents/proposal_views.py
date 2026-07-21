from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from core.mixins import CompanyScopedQuerysetMixin

from .forms import LineItemForm
from .models import Document, LineItem
from .pdf import build_proposal_pdf
from .proposal_forms import (
    ProposalCreateForm,
    ProposalEditForm,
    ProposalSectionForm,
    RetainerInvoiceForm,
)
from .proposal_services import (
    delete_proposal_section,
    save_proposal_section,
    withdraw_proposal,
)
from .services import delete_draft_document, delete_line_item, issue_document


def scoped_proposal(request, pk, *, draft=False):
    queryset = Document.objects.for_company(request.user.company).filter(
        doc_type=Document.Type.PROPOSAL
    )
    if draft:
        queryset = queryset.filter(status=Document.Status.DRAFT)
    return get_object_or_404(queryset.select_related("project", "project__client"), pk=pk)


class ProposalListView(LoginRequiredMixin, CompanyScopedQuerysetMixin, ListView):
    model = Document
    context_object_name = "proposals"
    template_name = "documents/proposal_list.html"

    def get_queryset(self):
        queryset = super().get_queryset().filter(doc_type=Document.Type.PROPOSAL)
        status = self.request.GET.get("status")
        project = self.request.GET.get("project")
        if status in Document.Status.values:
            queryset = queryset.filter(status=status)
        if project:
            queryset = queryset.filter(project_id=project)
        return queryset.select_related("project", "project__client").prefetch_related(
            "project__client__contacts"
        )


class ProposalDetailView(LoginRequiredMixin, CompanyScopedQuerysetMixin, DetailView):
    model = Document
    context_object_name = "proposal"
    template_name = "documents/proposal_detail.html"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(doc_type=Document.Type.PROPOSAL)
            .select_related("company", "project", "project__client")
            .prefetch_related(
                "project__client__contacts",
                "line_items",
                "derived_invoices",
                "deliveries",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["show_internal_notes"] = True
        return context


class ProposalCreateView(LoginRequiredMixin, CreateView):
    model = Document
    form_class = ProposalCreateForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "New proposal", "submit_label": "Create proposal"}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.request.user.company
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        if self.request.GET.get("project"):
            initial["project"] = self.request.GET["project"]
        return initial

    def get_success_url(self):
        return reverse("proposals:detail", args=(self.object.pk,))


class ProposalUpdateView(LoginRequiredMixin, CompanyScopedQuerysetMixin, UpdateView):
    model = Document
    form_class = ProposalEditForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "Edit proposal", "submit_label": "Save proposal"}

    def get_queryset(self):
        return super().get_queryset().filter(
            doc_type=Document.Type.PROPOSAL,
            status=Document.Status.DRAFT,
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.request.user.company
        return kwargs

    def get_success_url(self):
        return reverse("proposals:detail", args=(self.object.pk,))


class ProposalDeleteView(LoginRequiredMixin, View):
    def get(self, request, pk):
        proposal = scoped_proposal(request, pk, draft=True)
        return render(
            request,
            "shared/confirm_delete.html",
            {"object": proposal, "page_title": "Delete draft proposal"},
        )

    def post(self, request, pk):
        proposal = scoped_proposal(request, pk, draft=True)
        delete_draft_document(document=proposal)
        messages.success(request, "Draft proposal deleted.")
        return redirect("proposals:list")


class ProposalSectionView(LoginRequiredMixin, FormView):
    form_class = ProposalSectionForm
    template_name = "shared/form.html"
    proposal = None
    index = None

    def dispatch(self, request, *args, **kwargs):
        self.proposal = scoped_proposal(request, kwargs["proposal_pk"], draft=True)
        self.index = kwargs.get("index")
        if self.index is not None and self.index >= len(self.proposal.body_sections):
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        if self.index is None:
            return {}
        return self.proposal.body_sections[self.index]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            page_title="Add proposal section" if self.index is None else "Edit proposal section",
            submit_label="Save section",
        )
        return context

    def form_valid(self, form):
        save_proposal_section(
            proposal=self.proposal,
            heading=form.cleaned_data["heading"],
            body=form.cleaned_data["body"],
            index=self.index,
        )
        return redirect("proposals:detail", pk=self.proposal.pk)


class ProposalSectionDeleteView(LoginRequiredMixin, View):
    def post(self, request, proposal_pk, index):
        proposal = scoped_proposal(request, proposal_pk, draft=True)
        delete_proposal_section(proposal=proposal, index=index)
        return redirect("proposals:detail", pk=proposal.pk)


class ProposalLineMixin(LoginRequiredMixin):
    proposal = None

    def dispatch(self, request, *args, **kwargs):
        self.proposal = scoped_proposal(request, kwargs["proposal_pk"], draft=True)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["document"] = self.proposal
        return kwargs

    def get_success_url(self):
        return reverse("proposals:detail", args=(self.proposal.pk,))


class ProposalLineCreateView(ProposalLineMixin, CreateView):
    model = LineItem
    form_class = LineItemForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "Add proposal price", "submit_label": "Add price"}


class ProposalLineUpdateView(ProposalLineMixin, UpdateView):
    model = LineItem
    form_class = LineItemForm
    template_name = "shared/form.html"
    pk_url_kwarg = "line_pk"
    extra_context = {"page_title": "Edit proposal price", "submit_label": "Save price"}

    def get_queryset(self):
        return self.proposal.line_items.all()


class ProposalLineDeleteView(LoginRequiredMixin, View):
    def post(self, request, proposal_pk, line_pk):
        proposal = scoped_proposal(request, proposal_pk, draft=True)
        line = get_object_or_404(proposal.line_items, pk=line_pk)
        delete_line_item(line=line)
        return redirect("proposals:detail", pk=proposal.pk)


@login_required
@require_POST
def proposal_issue(request, pk):
    proposal = scoped_proposal(request, pk, draft=True)
    try:
        issue_document(document=proposal)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(request, "Proposal issued. Its public link is active.")
    return redirect("proposals:detail", pk=proposal.pk)


@login_required
@require_POST
def proposal_withdraw(request, pk):
    proposal = scoped_proposal(request, pk)
    try:
        withdraw_proposal(proposal=proposal)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("proposals:detail", pk=proposal.pk)


class RetainerCreateView(LoginRequiredMixin, FormView):
    form_class = RetainerInvoiceForm
    template_name = "shared/form.html"
    proposal = None
    extra_context = {"page_title": "Create retainer invoice", "submit_label": "Create retainer"}

    def dispatch(self, request, *args, **kwargs):
        self.proposal = scoped_proposal(request, kwargs["pk"])
        if self.proposal.status != Document.Status.ACCEPTED:
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["proposal"] = self.proposal
        return kwargs

    def form_valid(self, form):
        try:
            invoice = form.save()
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
            return self.form_invalid(form)
        return redirect("documents:invoice-detail", pk=invoice.pk)


class ProposalPdfView(LoginRequiredMixin, View):
    def get(self, request, pk):
        proposal = scoped_proposal(request, pk)
        response = HttpResponse(build_proposal_pdf(proposal), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{proposal.number}.pdf"'
        return response
