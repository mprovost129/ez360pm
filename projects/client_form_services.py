from copy import copy

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from documents.delivery_services import (
    deliver_transactional_email,
    delivery_error_is_uncertain,
)
from documents.models import DocumentDelivery

from .models import (
    ClientFormQuestion,
    ProjectClientForm,
    ProjectFormAnswer,
    ProjectFormQuestion,
    ProjectFormUpload,
)


@transaction.atomic
def save_template_question(*, template, question=None, data):
    if question is not None and question.template_id != template.pk:
        raise ValidationError("Question does not belong to this template.")
    if question is None:
        order = template.questions.aggregate(value=Max("order"))["value"] or 0
        question = ClientFormQuestion(template=template, order=order + 1)
    for field, value in data.items():
        setattr(question, field, value)
    question.full_clean()
    question.save()
    return question


@transaction.atomic
def move_template_question(*, question, direction):
    questions = list(
        ClientFormQuestion.objects.select_for_update()
        .filter(template=question.template)
        .order_by("order", "pk")
    )
    current = next(index for index, item in enumerate(questions) if item.pk == question.pk)
    question = questions[current]
    target_index = current - 1 if direction == "up" else current + 1
    if direction not in {"up", "down"} or target_index < 0 or target_index >= len(questions):
        return question
    target = questions[target_index]
    old_order = question.order
    target_order = target.order
    question.order = 0
    question.save(update_fields=["order"])
    target.order = old_order
    target.save(update_fields=["order"])
    question.order = target_order
    question.save(update_fields=["order"])
    return question


@transaction.atomic
def create_project_client_form(*, project, template, data):
    if project.company_id != template.company_id:
        raise ValidationError("Project and form template must belong to the same company.")
    questions = list(template.questions.all())
    if not questions:
        raise ValidationError("Add at least one question before sending this template.")
    project_form = ProjectClientForm(
        company=project.company,
        project=project,
        template=template,
        title=template.name,
        welcome_message=template.welcome_message,
        estimated_minutes=template.estimated_minutes,
        **data,
    )
    project_form.full_clean()
    project_form.save()
    ProjectFormQuestion.objects.bulk_create(
        [
            ProjectFormQuestion(
                project_form=project_form,
                source_question=question,
                section=question.section,
                label=question.label,
                help_text=question.help_text,
                field_type=question.field_type,
                required=question.required,
                options=list(question.options or []),
                order=question.order,
            )
            for question in questions
        ]
    )
    return project_form


def public_project_form_url(project_form):
    path = reverse("public-project-form", args=(project_form.public_token,))
    return f"{settings.PUBLIC_BASE_URL}{path}"


def send_project_client_form(*, project_form):
    project_form = ProjectClientForm.objects.select_related(
        "company", "project", "project__client"
    ).get(pk=project_form.pk)
    if project_form.status == ProjectClientForm.Status.SUBMITTED:
        raise ValidationError("Submitted forms cannot be resent.")
    subject = project_form.email_subject.strip() or (
        f"{project_form.title} for {project_form.project.name} from {project_form.company.name}"
    )
    delivery = project_form.email_deliveries.order_by("-created_at", "-pk").first()
    uncertain_retry = bool(
        delivery
        and delivery.purpose == DocumentDelivery.Purpose.CLIENT_FORM
        and delivery.status == DocumentDelivery.Status.FAILED
        and delivery_error_is_uncertain(delivery)
    )
    if uncertain_retry:
        subject = delivery.subject
        email_form = copy(project_form)
        email_form.recipient_name = delivery.recipient_name
        email_form.recipient_email = delivery.recipient_email
        email_form.email_message = delivery.message
    else:
        delivery = DocumentDelivery.objects.create(
            project_form=project_form,
            purpose=DocumentDelivery.Purpose.CLIENT_FORM,
            recipient_name=project_form.recipient_name,
            recipient_email=project_form.recipient_email,
            subject=subject,
            message=project_form.email_message,
        )
        email_form = project_form
    context = {
        "project_form": email_form,
        "form_url": public_project_form_url(project_form),
        "company_logo_url": (
            f"{settings.PUBLIC_BASE_URL}{project_form.company.logo.url}"
            if project_form.company.logo
            else ""
        ),
    }
    reply_to = project_form.company.email or settings.DEFAULT_REPLY_TO_EMAIL
    delivery = deliver_transactional_email(
        delivery=delivery,
        subject=subject,
        text_body=render_to_string("projects/email/client_form.txt", context),
        html_body=render_to_string("projects/email/client_form.html", context),
        reply_to=(reply_to,) if reply_to else (),
    )
    if delivery.status == DocumentDelivery.Status.SENT:
        project_form.email_status = ProjectClientForm.EmailStatus.SENT
        project_form.email_error = ""
        project_form.status = ProjectClientForm.Status.SENT
        project_form.sent_at = delivery.sent_at
        project_form.revoked_at = None
    else:
        project_form.email_status = ProjectClientForm.EmailStatus.FAILED
        project_form.email_error = delivery.error_code
    project_form.save(
        update_fields=[
            "email_status",
            "email_error",
            "status",
            "sent_at",
            "revoked_at",
            "updated_at",
        ]
    )
    return project_form


def _save_project_form_upload(*, question, uploaded_file):
    original_name = uploaded_file.name.replace("\\", "/").rsplit("/", 1)[-1][:255]
    try:
        upload = question.upload
    except ProjectFormUpload.DoesNotExist:
        upload = ProjectFormUpload(question=question)
        old_name = ""
        storage = None
    else:
        old_name = upload.file.name
        storage = upload.file.storage
    upload.file = uploaded_file
    upload.original_name = original_name
    upload.content_type = (getattr(uploaded_file, "content_type", "") or "")[:255]
    upload.size = uploaded_file.size
    upload.save()
    if old_name and old_name != upload.file.name:
        transaction.on_commit(lambda: storage.delete(old_name))
    return upload


@transaction.atomic
def save_project_form_answers(*, project_form, cleaned_data, submit):
    project_form = ProjectClientForm.objects.select_for_update().get(pk=project_form.pk)
    if project_form.status == ProjectClientForm.Status.SUBMITTED:
        raise ValidationError("This form has already been submitted.")
    for question in project_form.questions.all():
        value = cleaned_data.get(f"question_{question.pk}", "")
        if question.field_type == ClientFormQuestion.FieldType.FILE:
            if value:
                _save_project_form_upload(question=question, uploaded_file=value)
            continue
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        elif value is not None and not isinstance(value, (str, list, dict, bool, int, float)):
            value = str(value)
        ProjectFormAnswer.objects.update_or_create(question=question, defaults={"value": value})
    now = timezone.now()
    project_form.saved_at = now
    update_fields = ["saved_at", "updated_at"]
    if submit:
        project_form.status = ProjectClientForm.Status.SUBMITTED
        project_form.submitted_at = now
        update_fields.extend(["status", "submitted_at"])
    elif project_form.status == ProjectClientForm.Status.SENT:
        project_form.status = ProjectClientForm.Status.VIEWED
        update_fields.append("status")
    project_form.save(update_fields=update_fields)
    return project_form


@transaction.atomic
def set_project_form_access(*, project_form, active):
    project_form = ProjectClientForm.objects.select_for_update().get(pk=project_form.pk)
    if project_form.status == ProjectClientForm.Status.DRAFT:
        raise ValidationError("The client link is not active until the form is sent.")
    project_form.revoked_at = None if active else timezone.now()
    project_form.save(update_fields=["revoked_at", "updated_at"])
    return project_form


def send_project_form_submission_notification(*, project_form):
    project_form = ProjectClientForm.objects.select_related(
        "company", "project", "project__client"
    ).get(pk=project_form.pk)
    if (
        project_form.status != ProjectClientForm.Status.SUBMITTED
        or project_form.submission_notified_at
    ):
        return False
    recipient = project_form.company.email or (
        project_form.company.users.filter(is_active=True)
        .exclude(email="")
        .values_list("email", flat=True)
        .first()
    )
    if not recipient:
        return False
    context = {
        "project_form": project_form,
        "detail_url": (
            f"{settings.PUBLIC_BASE_URL}"
            f"{reverse('projects:client-form-detail', args=(project_form.project_id, project_form.pk))}"
        ),
    }
    subject = f"Form submitted: {project_form.title} - {project_form.project.name}"
    delivery, created = DocumentDelivery.objects.get_or_create(
        dedupe_key=f"project-form-submission:{project_form.pk}",
        defaults={
            "project_form": project_form,
            "purpose": DocumentDelivery.Purpose.CLIENT_FORM_SUBMISSION,
            "recipient_name": project_form.company.name,
            "recipient_email": recipient,
            "subject": subject,
        },
    )
    if not created and delivery.status not in {
        DocumentDelivery.Status.PENDING,
        DocumentDelivery.Status.FAILED,
    }:
        return True
    delivery = deliver_transactional_email(
        delivery=delivery,
        subject=subject,
        text_body=render_to_string("projects/email/client_form_submitted.txt", context),
        html_body=render_to_string("projects/email/client_form_submitted.html", context),
        reply_to=(
            (settings.DEFAULT_REPLY_TO_EMAIL,)
            if settings.DEFAULT_REPLY_TO_EMAIL
            else ()
        ),
    )
    if delivery.status != DocumentDelivery.Status.SENT:
        return False
    ProjectClientForm.objects.filter(
        pk=project_form.pk,
        submission_notified_at__isnull=True,
    ).update(submission_notified_at=timezone.now())
    return True
