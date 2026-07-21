from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.decorators.http import require_POST

from .delivery_services import public_document_url, send_acceptance_notification
from .models import Document
from .pdf import build_invoice_pdf, build_proposal_pdf
from .proposal_forms import AcceptanceForm
from .proposal_services import accept_proposal, decline_proposal
from .public_security import public_action_rate_limited
from .services import record_public_view
from .stripe_services import stripe_configuration_status


def public_document(token):
    queryset = (
        Document.objects.exclude(status=Document.Status.DRAFT)
        .select_related("company", "project", "project__client")
        .prefetch_related(
            "project__client__contacts",
            "line_items",
            "payments",
            "credits_received__source_invoice",
        )
    )
    return get_object_or_404(queryset, public_token=token)


class PublicDocumentView(View):
    def get(self, request, token):
        document = record_public_view(document=public_document(token))
        if document.doc_type == Document.Type.INVOICE:
            stripe_status = stripe_configuration_status()
            return render(
                request,
                "documents/public_invoice.html",
                {
                    "invoice": document,
                    "payment_submitted": request.GET.get("payment") == "success",
                    "stripe_available": (
                        stripe_status["configured"]
                        and document.accept_payments
                        and document.status
                        in {
                            Document.Status.SENT,
                            Document.Status.VIEWED,
                            Document.Status.PARTIALLY_PAID,
                        }
                        and document.outstanding_balance > 0
                    ),
                },
            )
        return render(
            request,
            "documents/public_proposal.html",
            {
                "proposal": document,
                "acceptance_form": AcceptanceForm(),
            },
        )


@require_POST
def public_proposal_accept(request, token):
    if public_action_rate_limited(request=request, token=token, action="accept"):
        return HttpResponse("Too many attempts. Please wait and try again.", status=429)
    proposal = public_document(token)
    if proposal.doc_type != Document.Type.PROPOSAL:
        return redirect("public-documents:view", token=token)
    form = AcceptanceForm(request.POST)
    if form.is_valid():
        was_open = proposal.status in {Document.Status.SENT, Document.Status.VIEWED}
        try:
            accept_proposal(
                proposal=proposal,
                signer_name=form.cleaned_data["signer_name"],
                signer_email=form.cleaned_data["signer_email"],
                ip_address=request.META.get("REMOTE_ADDR"),
            )
        except ValidationError as exc:
            form.add_error(None, exc.message)
        else:
            if was_open:
                send_acceptance_notification(
                    proposal=proposal,
                    document_url=public_document_url(proposal),
                )
            return redirect("public-documents:view", token=token)
    proposal.refresh_from_db()
    return render(
        request,
        "documents/public_proposal.html",
        {"proposal": proposal, "acceptance_form": form},
        status=400,
    )


@require_POST
def public_proposal_decline(request, token):
    if public_action_rate_limited(request=request, token=token, action="decline"):
        return HttpResponse("Too many attempts. Please wait and try again.", status=429)
    proposal = public_document(token)
    if proposal.doc_type == Document.Type.PROPOSAL:
        try:
            decline_proposal(proposal=proposal)
        except ValidationError:
            pass
    return redirect("public-documents:view", token=token)


class PublicDocumentPdfView(View):
    def get(self, request, token):
        document = public_document(token)
        if document.doc_type == Document.Type.PROPOSAL:
            content = build_proposal_pdf(document)
        else:
            content = build_invoice_pdf(document)
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{document.number}.pdf"'
        return response
