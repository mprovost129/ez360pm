import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Max
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from documents.delivery_services import email_configuration_status

from .models import (
    ClientFormQuestion,
    ProjectClientForm,
    ProjectFormAnswer,
    ProjectFormQuestion,
)

logger = logging.getLogger(__name__)


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
    if not email_configuration_status()["configured"]:
        project_form.email_status = ProjectClientForm.EmailStatus.FAILED
        project_form.email_error = "email_not_configured"
        project_form.save(update_fields=["email_status", "email_error", "updated_at"])
        return project_form
    subject = project_form.email_subject.strip() or (
        f"{project_form.title} for {project_form.project.name} from {project_form.company.name}"
    )
    context = {
        "project_form": project_form,
        "form_url": public_project_form_url(project_form),
        "company_logo_url": (
            f"{settings.PUBLIC_BASE_URL}{project_form.company.logo.url}"
            if project_form.company.logo
            else ""
        ),
    }
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string("projects/email/client_form.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[project_form.recipient_email],
        reply_to=[project_form.company.email] if project_form.company.email else None,
    )
    message.attach_alternative(
        render_to_string("projects/email/client_form.html", context),
        "text/html",
    )
    try:
        sent_count = message.send(fail_silently=False)
    except Exception as exc:
        logger.warning("Project form email failed form_id=%s error=%s", project_form.pk, exc.__class__.__name__)
        project_form.email_status = ProjectClientForm.EmailStatus.FAILED
        project_form.email_error = exc.__class__.__name__.lower()[:100]
    else:
        if sent_count == 1:
            project_form.email_status = ProjectClientForm.EmailStatus.SENT
            project_form.email_error = ""
            project_form.status = ProjectClientForm.Status.SENT
            project_form.sent_at = timezone.now()
        else:
            project_form.email_status = ProjectClientForm.EmailStatus.FAILED
            project_form.email_error = "provider_did_not_confirm_send"
    project_form.save(
        update_fields=["email_status", "email_error", "status", "sent_at", "updated_at"]
    )
    return project_form


@transaction.atomic
def save_project_form_answers(*, project_form, cleaned_data, submit):
    project_form = ProjectClientForm.objects.select_for_update().get(pk=project_form.pk)
    if project_form.status == ProjectClientForm.Status.SUBMITTED:
        raise ValidationError("This form has already been submitted.")
    for question in project_form.questions.all():
        value = cleaned_data.get(f"question_{question.pk}", "")
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
