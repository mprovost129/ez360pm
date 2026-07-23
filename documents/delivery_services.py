import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import Document, DocumentDelivery, Payment

logger = logging.getLogger(__name__)


def public_document_url(document):
    path = reverse("public-documents:view", args=(document.public_token,))
    return f"{settings.PUBLIC_BASE_URL}{path}"


def email_configuration_status():
    backend = settings.EMAIL_BACKEND
    if backend.endswith("smtp.EmailBackend"):
        configured = bool(
            settings.EMAIL_HOST
            and settings.EMAIL_HOST_USER
            and settings.EMAIL_HOST_PASSWORD
            and settings.DEFAULT_FROM_EMAIL != "webmaster@localhost"
        )
    else:
        configured = bool(backend)
    return {
        "configured": configured,
        "backend": backend.rsplit(".", 1)[-1],
        "from_email": settings.DEFAULT_FROM_EMAIL,
    }


def _mark_failed(delivery, error_code):
    delivery.status = DocumentDelivery.Status.FAILED
    delivery.error_code = error_code[:100]
    delivery.save(update_fields=["status", "error_code"])
    return delivery


def _send_delivery(*, delivery, subject, document_url, template_base, context):
    if not email_configuration_status()["configured"]:
        return _mark_failed(delivery, "email_not_configured")
    context = {**context, "document_url": document_url}
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string(f"documents/email/{template_base}.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[delivery.recipient_email],
        reply_to=[delivery.document.company.email] if delivery.document.company.email else None,
    )
    message.attach_alternative(
        render_to_string(f"documents/email/{template_base}.html", context),
        "text/html",
    )
    try:
        sent_count = message.send(fail_silently=False)
    except Exception as exc:  # provider exceptions vary by configured backend
        logger.warning(
            "Document delivery failed document_id=%s delivery_id=%s error=%s",
            delivery.document_id,
            delivery.pk,
            exc.__class__.__name__,
        )
        return _mark_failed(delivery, exc.__class__.__name__.lower())
    if sent_count != 1:
        return _mark_failed(delivery, "provider_did_not_confirm_send")
    delivery.status = DocumentDelivery.Status.SENT
    delivery.sent_at = timezone.now()
    delivery.error_code = ""
    delivery.save(update_fields=["status", "sent_at", "error_code"])
    return delivery


def send_document_email(*, document, recipient_name, recipient_email, document_url):
    document = Document.objects.select_related("company", "project", "project__client").get(
        pk=document.pk
    )
    allowed = {
        Document.Type.PROPOSAL: {
            Document.Status.SENT,
            Document.Status.VIEWED,
            Document.Status.ACCEPTED,
        },
        Document.Type.INVOICE: {
            Document.Status.SENT,
            Document.Status.VIEWED,
            Document.Status.PARTIALLY_PAID,
            Document.Status.PAID,
        },
    }
    if document.status not in allowed[document.doc_type]:
        raise ValueError("Only open, issued documents can be emailed.")
    recipient_name = recipient_name.strip()
    recipient_email = recipient_email.strip().lower()
    validate_email(recipient_email)
    delivery = DocumentDelivery.objects.create(
        document=document,
        purpose=DocumentDelivery.Purpose.CLIENT_DOCUMENT,
        recipient_name=recipient_name,
        recipient_email=recipient_email,
    )
    label = document.get_doc_type_display()
    return _send_delivery(
        delivery=delivery,
        subject=f"{label} {document.number} from {document.company.name}",
        document_url=document_url,
        template_base="document_delivery",
        context={"document": document, "recipient_name": recipient_name},
    )


def send_acceptance_notification(*, proposal, document_url):
    proposal = Document.objects.select_related("company", "project", "project__client").get(
        pk=proposal.pk
    )
    recipient_email = proposal.company.email
    if not recipient_email:
        recipient_email = (
            proposal.company.users.order_by("is_superuser", "pk")
            .values_list("email", flat=True)
            .first()
            or ""
        )
    if not recipient_email:
        return None
    delivery = DocumentDelivery.objects.create(
        document=proposal,
        purpose=DocumentDelivery.Purpose.ACCEPTANCE_NOTIFICATION,
        recipient_name=proposal.company.name,
        recipient_email=recipient_email,
    )
    return _send_delivery(
        delivery=delivery,
        subject=f"Proposal {proposal.number} accepted",
        document_url=document_url,
        template_base="acceptance_notification",
        context={"proposal": proposal},
    )


def send_payment_notification(*, payment):
    payment = Payment.objects.select_related(
        "document",
        "document__company",
        "document__project",
        "document__project__client",
    ).get(pk=payment.pk)
    invoice = payment.document
    recipient_email = invoice.company.email
    if not recipient_email:
        recipient_email = (
            invoice.company.users.order_by("is_superuser", "pk")
            .values_list("email", flat=True)
            .first()
            or ""
        )
    if not recipient_email:
        return None

    dedupe_key = f"stripe-payment:{payment.stripe_payment_intent_id}"
    delivery, created = DocumentDelivery.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={
            "document": invoice,
            "purpose": DocumentDelivery.Purpose.PAYMENT_NOTIFICATION,
            "recipient_name": invoice.company.name,
            "recipient_email": recipient_email,
        },
    )
    if not created:
        return delivery
    return _send_delivery(
        delivery=delivery,
        subject=f"Payment received for invoice {invoice.number}",
        document_url=public_document_url(invoice),
        template_base="payment_notification",
        context={"invoice": invoice, "payment": payment},
    )
