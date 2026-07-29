from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from documents.public_security import public_action_rate_limited

from .client_form_forms import (
    ClientFormQuestionForm,
    ClientFormTemplateForm,
    ProjectClientFormDeliveryForm,
    ProjectClientFormSendForm,
    PublicProjectFormResponseForm,
)
from .client_form_services import (
    create_project_client_form,
    move_template_question,
    save_project_form_answers,
    save_template_question,
    send_project_client_form,
)
from .models import (
    ClientFormTemplate,
    Project,
    ProjectClientForm,
    ProjectFormAnswer,
)


def _template_for_user(request, pk):
    return get_object_or_404(
        ClientFormTemplate.objects.for_company(request.user.company), pk=pk
    )


def _project_for_user(request, pk):
    return get_object_or_404(
        Project.objects.for_company(request.user.company).select_related("client"), pk=pk
    )


def _project_form_for_user(request, pk, form_pk):
    return get_object_or_404(
        ProjectClientForm.objects.for_company(request.user.company)
        .select_related("project", "project__client", "template", "company")
        .prefetch_related("questions__answer"),
        pk=form_pk,
        project_id=pk,
    )


def _answer_sections(project_form):
    sections = []
    for question in project_form.questions.all():
        section = question.section or "Project information"
        if not sections or sections[-1][0] != section:
            sections.append((section, []))
        try:
            value = question.answer.value
        except ProjectFormAnswer.DoesNotExist:
            value = ""
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        elif value == "yes":
            value = "Yes"
        elif value == "no":
            value = "No"
        sections[-1][1].append((question, value))
    return sections


class ClientFormTemplateListView(LoginRequiredMixin, ListView):
    model = ClientFormTemplate
    template_name = "projects/form_template_list.html"
    context_object_name = "form_templates"

    def get_queryset(self):
        return ClientFormTemplate.objects.for_company(self.request.user.company).prefetch_related(
            "questions"
        )


class ClientFormTemplateCreateView(LoginRequiredMixin, CreateView):
    model = ClientFormTemplate
    form_class = ClientFormTemplateForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "New client form template", "submit_label": "Create template"}

    def form_valid(self, form):
        form.instance.company = self.request.user.company
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("projects:form-template-detail", args=(self.object.pk,))


class ClientFormTemplateDetailView(LoginRequiredMixin, DetailView):
    model = ClientFormTemplate
    template_name = "projects/form_template_detail.html"
    context_object_name = "form_template"

    def get_queryset(self):
        return ClientFormTemplate.objects.for_company(self.request.user.company).prefetch_related(
            "questions"
        )


class ClientFormTemplateUpdateView(LoginRequiredMixin, UpdateView):
    model = ClientFormTemplate
    form_class = ClientFormTemplateForm
    template_name = "shared/form.html"
    extra_context = {"page_title": "Edit client form template", "submit_label": "Save template"}

    def get_queryset(self):
        return ClientFormTemplate.objects.for_company(self.request.user.company)

    def get_success_url(self):
        return reverse("projects:form-template-detail", args=(self.object.pk,))


class ClientFormQuestionView(LoginRequiredMixin, FormView):
    form_class = ClientFormQuestionForm
    template_name = "shared/form.html"
    template = None
    question = None

    def dispatch(self, request, *args, **kwargs):
        self.template = _template_for_user(request, kwargs["template_pk"])
        if "question_pk" in kwargs:
            self.question = get_object_or_404(
                self.template.questions, pk=kwargs["question_pk"]
            )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.question:
            kwargs["instance"] = self.question
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Edit question" if self.question else "Add question"
        context["submit_label"] = "Save question"
        return context

    def form_valid(self, form):
        data = {field: form.cleaned_data[field] for field in form.Meta.fields}
        data["options"] = form.cleaned_data["options"]
        save_template_question(
            template=self.template,
            question=self.question,
            data=data,
        )
        return redirect("projects:form-template-detail", pk=self.template.pk)


class ClientFormQuestionDeleteView(LoginRequiredMixin, View):
    def post(self, request, template_pk, question_pk):
        template = _template_for_user(request, template_pk)
        question = get_object_or_404(template.questions, pk=question_pk)
        question.delete()
        messages.success(request, "Question removed from the template.")
        return redirect("projects:form-template-detail", pk=template.pk)


class ClientFormQuestionMoveView(LoginRequiredMixin, View):
    def post(self, request, template_pk, question_pk, direction):
        template = _template_for_user(request, template_pk)
        question = get_object_or_404(template.questions, pk=question_pk)
        move_template_question(question=question, direction=direction)
        return redirect("projects:form-template-detail", pk=template.pk)


class ProjectClientFormCreateView(LoginRequiredMixin, FormView):
    form_class = ProjectClientFormSendForm
    template_name = "shared/form.html"
    project = None
    extra_context = {"page_title": "New client form", "submit_label": "Create & email form"}

    def dispatch(self, request, *args, **kwargs):
        self.project = _project_for_user(request, kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(company=self.request.user.company, project=self.project)
        return kwargs

    def form_valid(self, form):
        try:
            project_form = create_project_client_form(
                project=self.project,
                template=form.cleaned_data["template"],
                data={
                    "recipient_name": form.cleaned_data["recipient_name"],
                    "recipient_email": form.cleaned_data["recipient_email"],
                    "email_subject": form.cleaned_data["email_subject"],
                    "email_message": form.cleaned_data["email_message"],
                },
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
            return self.form_invalid(form)
        project_form = send_project_client_form(project_form=project_form)
        if project_form.email_status == ProjectClientForm.EmailStatus.SENT:
            messages.success(self.request, f"Client form emailed to {project_form.recipient_email}.")
        else:
            messages.error(self.request, "The form was created, but its email was not sent. Review email settings and resend it.")
        return redirect(
            "projects:client-form-detail", pk=self.project.pk, form_pk=project_form.pk
        )


class ProjectClientFormDetailView(LoginRequiredMixin, View):
    def get(self, request, pk, form_pk):
        project_form = _project_form_for_user(request, pk, form_pk)
        return render(
            request,
            "projects/client_form_detail.html",
            {"project_form": project_form, "answer_sections": _answer_sections(project_form)},
        )


class ProjectClientFormUpdateView(LoginRequiredMixin, UpdateView):
    model = ProjectClientForm
    form_class = ProjectClientFormDeliveryForm
    template_name = "shared/form.html"
    pk_url_kwarg = "form_pk"
    extra_context = {"page_title": "Edit client form delivery", "submit_label": "Save delivery"}

    def get_queryset(self):
        return ProjectClientForm.objects.for_company(self.request.user.company).filter(
            project_id=self.kwargs["pk"]
        ).exclude(status=ProjectClientForm.Status.SUBMITTED)

    def get_success_url(self):
        return reverse(
            "projects:client-form-detail",
            args=(self.object.project_id, self.object.pk),
        )


class ProjectClientFormResendView(LoginRequiredMixin, View):
    def post(self, request, pk, form_pk):
        project_form = _project_form_for_user(request, pk, form_pk)
        try:
            project_form = send_project_client_form(project_form=project_form)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            if project_form.email_status == ProjectClientForm.EmailStatus.SENT:
                messages.success(request, f"Client form emailed to {project_form.recipient_email}.")
            else:
                messages.error(request, "The email was not sent.")
        return redirect("projects:client-form-detail", pk=pk, form_pk=form_pk)


class ProjectSpecificationsView(LoginRequiredMixin, View):
    def get(self, request, pk):
        project = _project_for_user(request, pk)
        project_forms = list(
            ProjectClientForm.objects.for_company(request.user.company)
            .filter(project=project)
            .select_related("template")
            .prefetch_related("questions__answer")
        )
        form_sections = [(item, _answer_sections(item)) for item in project_forms]
        return render(
            request,
            "projects/project_specifications.html",
            {"project": project, "form_sections": form_sections},
        )


class PublicProjectClientFormView(View):
    template_name = "projects/public_client_form.html"

    def _form(self, token):
        return get_object_or_404(
            ProjectClientForm.objects.select_related(
                "company", "project", "project__client"
            ).prefetch_related("questions__answer"),
            public_token=token,
        )

    def get(self, request, token):
        project_form = self._form(token)
        if project_form.status == ProjectClientForm.Status.DRAFT:
            raise Http404
        if project_form.status == ProjectClientForm.Status.SENT:
            project_form.status = ProjectClientForm.Status.VIEWED
            project_form.viewed_at = timezone.now()
            project_form.save(update_fields=["status", "viewed_at", "updated_at"])
        response_form = None
        if project_form.status != ProjectClientForm.Status.SUBMITTED:
            response_form = PublicProjectFormResponseForm(
                project_form=project_form,
                require_complete=False,
            )
        return render(request, self.template_name, {"project_form": project_form, "form": response_form})

    def post(self, request, token):
        if public_action_rate_limited(request=request, token=token, action="project-form", limit=30):
            return HttpResponse("Too many attempts. Please wait and try again.", status=429)
        project_form = self._form(token)
        if project_form.status in {ProjectClientForm.Status.DRAFT, ProjectClientForm.Status.SUBMITTED}:
            raise Http404
        submit = request.POST.get("action") == "submit"
        response_form = PublicProjectFormResponseForm(
            request.POST,
            project_form=project_form,
            require_complete=submit,
        )
        if response_form.is_valid():
            save_project_form_answers(
                project_form=project_form,
                cleaned_data=response_form.cleaned_data,
                submit=submit,
            )
            if submit:
                return redirect("public-project-form", token=token)
            return redirect(f"{reverse('public-project-form', args=(token,))}?saved=1")
        return render(
            request,
            self.template_name,
            {"project_form": project_form, "form": response_form},
            status=400,
        )
