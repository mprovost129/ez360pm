import logging

from django.conf import settings
from django.core.validators import validate_email
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from core.emailing import (
    EmailDeliveryError,
    TransactionalEmail,
    send_transactional_email,
)

from .models import Document, DocumentDelivery, Payment

logger = logging.getLogger(__name__)

UNCERTAIN_DELIVERY_ERROR_TOKENS = ("timeout", "connection", "socket", "interrupted")


def public_document_url(document):
    path = reverse("public-documents:view", args=(document.public_token,))
    return f"{settings.PUBLIC_BASE_URL}{path}"


def email_configuration_status():
    provider = settings.EMAIL_PROVIDER.strip().lower()
    backend = settings.EMAIL_BACKEND
    if provider == "resend":
        configured = bool(
            settings.RESEND_API_KEY
            and backend == "core.email_backends.ResendEmailBackend"
            and settings.DEFAULT_FROM_EMAIL != "webmaster@localhost"
        )
    elif provider == "django" and backend.endswith("smtp.EmailBackend"):
        configured = bool(
            settings.EMAIL_HOST
            and settings.EMAIL_HOST_USER
            and settings.EMAIL_HOST_PASSWORD
            and settings.DEFAULT_FROM_EMAIL != "webmaster@localhost"
        )
    elif provider == "django":
        configured = bool(backend)
    else:
        configured = False
    return {
        "configured": configured,
        "provider": provider,
        "backend": backend.rsplit(".", 1)[-1],
        "from_email": settings.DEFAULT_FROM_EMAIL,
        "reply_to_email": settings.DEFAULT_REPLY_TO_EMAIL,
        "api_key": bool(settings.RESEND_API_KEY),
        "webhook_secret": bool(settings.RESEND_WEBHOOK_SECRET),
    }


def _mark_failed(delivery, error_code):
    delivery.status = DocumentDelivery.Status.FAILED
    delivery.error_code = error_code[:100]
    delivery.save(update_fields=["status", "error_code"])
    return delivery


def deliver_transactional_email(
    *, delivery, subject, text_body, html_body, reply_to=()
):
    if not email_configuration_status()["configured"]:
        return _mark_failed(delivery, "email_not_configured")
    try:
        result = send_transactional_email(
            TransactionalEmail(
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=(delivery.recipient_email,),
                reply_to=tuple(reply_to),
                idempotency_key=f"delivery/{delivery.pk}",
            )
        )
    except EmailDeliveryError as exc:
        logger.warning(
            "Email delivery failed document_id=%s project_form_id=%s delivery_id=%s error=%s",
            delivery.document_id,
            delivery.project_form_id,
            delivery.pk,
            exc.code,
        )
        return _mark_failed(delivery, exc.code)
    delivery.status = DocumentDelivery.Status.SENT
    delivery.sent_at = timezone.now()
    delivery.error_code = ""
    delivery.provider = result.provider
    delivery.provider_message_id = result.message_id
    delivery.save(
        update_fields=[
            "status",
            "sent_at",
            "error_code",
            "provider",
            "provider_message_id",
        ]
    )
    return delivery


def delivery_error_is_uncertain(delivery):
    code = delivery.error_code.lower()
    return any(token in code for token in UNCERTAIN_DELIVERY_ERROR_TOKENS)


def _send_delivery(*, delivery, subject, document_url, template_base, context):
    context = {**context, "document_url": document_url}
    company_email = delivery.document.company.email
    reply_to = company_email or settings.DEFAULT_REPLY_TO_EMAIL
    return deliver_transactional_email(
        delivery=delivery,
        subject=subject,
        text_body=render_to_string(f"documents/email/{template_base}.txt", context),
        html_body=render_to_string(f"documents/email/{template_base}.html", context),
        reply_to=(reply_to,) if reply_to else (),
    )


def send_document_email(
    *,
    document,
    recipient_name,
    recipient_email,
    document_url,
    subject="",
    message="",
    purpose=DocumentDelivery.Purpose.CLIENT_DOCUMENT,
    follow_up_kind="",
):
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
    if purpose not in {
        DocumentDelivery.Purpose.CLIENT_DOCUMENT,
        DocumentDelivery.Purpose.CLIENT_FOLLOW_UP,
    }:
        raise ValueError("Client email purpose is not supported.")
    if purpose == DocumentDelivery.Purpose.CLIENT_FOLLOW_UP:
        if follow_up_kind not in DocumentDelivery.FollowUpKind.values:
            raise ValueError("A recognized follow-up kind is required.")
    else:
        follow_up_kind = ""
    recipient_name = recipient_name.strip()
    recipient_email = recipient_email.strip().lower()
    validate_email(recipient_email)
    label = document.get_doc_type_display()
    subject = (subject or f"{label} {document.number} from {document.company.name}").strip()[:255]
    message = (message or "").strip()[:4000]
    delivery = DocumentDelivery.objects.create(
        document=document,
        purpose=purpose,
        follow_up_kind=follow_up_kind,
        recipient_name=recipient_name,
        recipient_email=recipient_email,
        subject=subject,
        message=message,
    )
    return _send_delivery(
        delivery=delivery,
        subject=subject,
        document_url=document_url,
        template_base="document_delivery",
        context={
            "document": document,
            "recipient_name": recipient_name,
            "custom_message": message,
        },
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


def send_decline_notification(*, proposal, document_url):
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
    delivery, created = DocumentDelivery.objects.get_or_create(
        dedupe_key=f"proposal-decline:{proposal.pk}",
        defaults={
            "document": proposal,
            "purpose": DocumentDelivery.Purpose.DECLINE_NOTIFICATION,
            "recipient_name": proposal.company.name,
            "recipient_email": recipient_email,
        },
    )
    if not created:
        return delivery
    return _send_delivery(
        delivery=delivery,
        subject=f"Proposal {proposal.number} declined",
        document_url=document_url,
        template_base="decline_notification",
        context={"proposal": proposal},
    )


def queue_payment_notification(*, payment):
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
    return delivery


def send_payment_notification(*, payment):
    delivery = queue_payment_notification(payment=payment)
    if delivery is None or delivery.status != DocumentDelivery.Status.PENDING:
        return delivery
    payment = Payment.objects.select_related(
        "document",
        "document__company",
        "document__project",
        "document__project__client",
    ).get(pk=payment.pk)
    invoice = payment.document
    return _send_delivery(
        delivery=delivery,
        subject=f"Payment received for invoice {invoice.number}",
        document_url=public_document_url(invoice),
        template_base="payment_notification",
        context={"invoice": invoice, "payment": payment},
    )


def resend_delivery_attempt(*, delivery):
    """Create a new auditable attempt for a client email or failed notification."""

    delivery = DocumentDelivery.objects.select_related(
        "document",
        "document__company",
        "document__project",
        "document__project__client",
    ).get(pk=delivery.pk)
    document = delivery.document
    if delivery.purpose == DocumentDelivery.Purpose.CLIENT_DOCUMENT:
        if delivery.status == DocumentDelivery.Status.PENDING:
            _mark_failed(delivery, "interrupted_before_provider_confirmation")
        if delivery_error_is_uncertain(delivery):
            return _send_delivery(
                delivery=delivery,
                subject=delivery.subject or (
                    f"{document.get_doc_type_display()} {document.number} "
                    f"from {document.company.name}"
                ),
                document_url=public_document_url(document),
                template_base="document_delivery",
                context={
                    "document": document,
                    "recipient_name": delivery.recipient_name,
                    "custom_message": delivery.message,
                },
            )
        return send_document_email(
            document=document,
            recipient_name=delivery.recipient_name,
            recipient_email=delivery.recipient_email,
            document_url=public_document_url(document),
        )
    if delivery.status not in {
        DocumentDelivery.Status.PENDING,
        DocumentDelivery.Status.FAILED,
    }:
        raise ValueError("Only pending or failed internal notifications can be retried.")

    repeated = delivery
    if delivery.status == DocumentDelivery.Status.FAILED:
        repeated = DocumentDelivery.objects.create(
            document=document,
            purpose=delivery.purpose,
            recipient_name=delivery.recipient_name,
            recipient_email=delivery.recipient_email,
        )
    document_url = public_document_url(document)
    if delivery.purpose == DocumentDelivery.Purpose.ACCEPTANCE_NOTIFICATION:
        return _send_delivery(
            delivery=repeated,
            subject=f"Proposal {document.number} accepted",
            document_url=document_url,
            template_base="acceptance_notification",
            context={"proposal": document},
        )
    if delivery.purpose == DocumentDelivery.Purpose.DECLINE_NOTIFICATION:
        return _send_delivery(
            delivery=repeated,
            subject=f"Proposal {document.number} declined",
            document_url=document_url,
            template_base="decline_notification",
            context={"proposal": document},
        )
    if delivery.purpose == DocumentDelivery.Purpose.PAYMENT_NOTIFICATION:
        payment_intent_id = delivery.dedupe_key.removeprefix("stripe-payment:")
        payment = document.payments.filter(
            stripe_payment_intent_id=payment_intent_id
        ).first()
        if payment is None:
            repeated.delete()
            raise ValueError("The payment for this notification no longer exists.")
        return _send_delivery(
            delivery=repeated,
            subject=f"Payment received for invoice {document.number}",
            document_url=document_url,
            template_base="payment_notification",
            context={"invoice": document, "payment": payment},
        )
    repeated.delete()
    raise ValueError("This delivery type cannot be retried.")
