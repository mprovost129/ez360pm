from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import FormView

from .delivery_forms import DocumentDeliveryForm
from .delivery_services import public_document_url, send_document_email
from .models import Document


class DocumentSendView(LoginRequiredMixin, FormView):
    form_class = DocumentDeliveryForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "Email document", "submit_label": "Send email"}
    doc_type = None
    success_url_name = None
    document = None

    def dispatch(self, request, *args, **kwargs):
        allowed_statuses = {
            Document.Type.PROPOSAL: (Document.Status.SENT, Document.Status.VIEWED),
            Document.Type.INVOICE: (
                Document.Status.SENT,
                Document.Status.VIEWED,
                Document.Status.PARTIALLY_PAID,
            ),
        }
        self.document = get_object_or_404(
            Document.objects.for_company(request.user.company)
            .filter(doc_type=self.doc_type, status__in=allowed_statuses[self.doc_type]),
            pk=kwargs["pk"],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        contact = self.document.project.client.primary_contact
        if contact:
            initial.update(
                recipient_name=contact.get_full_name(),
                recipient_email=contact.email,
            )
        return initial

    def form_valid(self, form):
        delivery = send_document_email(
            document=self.document,
            recipient_name=form.cleaned_data["recipient_name"],
            recipient_email=form.cleaned_data["recipient_email"],
            document_url=public_document_url(self.document),
        )
        if delivery.status == delivery.Status.SENT:
            messages.success(self.request, f"Email sent to {delivery.recipient_email}.")
        else:
            messages.error(
                self.request,
                f"Email was not sent. Delivery error: {delivery.error_code}.",
            )
        return redirect(self.success_url_name, pk=self.document.pk)
