import csv
import json
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import UpdateView

from .action_center import expire_pending_actions, pending_actions_for_user
from .draft_tracking import track_completed_draft_action
from .followups import follow_up_metrics, follow_up_rows
from .forms import AICompanySettingsForm
from .insights import (
    SUGGESTION_LIBRARY,
    command_suggestions,
    dismiss_insight,
    draft_quality_metrics,
    proactive_insights,
    record_event,
    usage_metrics,
)
from .models import (
    AIActionAttempt,
    AICompanySettings,
    AIDocumentDraftReview,
    AIEvaluationRun,
    AIEvent,
    AIFeedback,
    AIIncident,
    AIInteraction,
    AIUserAccess,
)
from .policies import (
    AIPolicyError,
    evaluate_failure_circuit_breaker,
    get_company_policy,
    require_assistant_available,
    require_risk_allowed,
    resume_company_ai,
    suspend_company_ai,
)
from .readiness import build_readiness_report
from .registry import registry
from .services import (
    AssistantRateLimited,
    AssistantUnavailable,
    run_assistant,
)


def _error(message, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def _csv_safe(value):
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def _parse_json(request):
    if len(request.body) > settings.AI_MAX_REQUEST_BYTES:
        raise ValidationError("The assistant request is too large.")
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError as exc:
        raise ValidationError("The assistant request was not valid JSON.") from exc


def _require_ai_admin(user):
    if not user.is_staff:
        raise PermissionDenied("Company AI pilot controls require a staff account.")


@login_required
@require_POST
def ask(request):
    try:
        payload = _parse_json(request)
        result = run_assistant(
            user=request.user,
            prompt=payload.get("prompt", ""),
            conversation_id=payload.get("conversation_id"),
            page_path=payload.get("page_path", ""),
        )
    except AssistantRateLimited as exc:
        return _error(str(exc), status=429)
    except AssistantUnavailable as exc:
        return _error(str(exc), status=503)
    except ValidationError as exc:
        return _error(" ".join(exc.messages))
    return JsonResponse(
        {
            "ok": True,
            "message": result.message,
            "links": result.links,
            "pending_actions": result.pending_actions,
            "interaction_id": result.interaction_id,
            "conversation_id": result.conversation_id,
        }
    )


@login_required
@require_GET
def assistant_home_data(request):
    policy = get_company_policy(request.user.company)
    try:
        require_assistant_available(policy, user=request.user)
    except AIPolicyError as exc:
        return _error(" ".join(exc.messages), status=503)
    insights = []
    if (
        getattr(settings, "AI_PROACTIVE_INSIGHTS_ENABLED", True)
        and policy.proactive_insights_enabled
    ):
        insights = proactive_insights(request.user)
    return JsonResponse(
        {
            "ok": True,
            "insights": insights,
            "suggestions": command_suggestions(request.user, policy=policy),
            "pending_actions": pending_actions_for_user(request.user),
            "refresh_seconds": settings.AI_PROACTIVE_REFRESH_SECONDS,
        }
    )


@login_required
@require_POST
def dismiss_proactive_insight(request):
    try:
        payload = _parse_json(request)
    except ValidationError as exc:
        return _error(" ".join(exc.messages))
    key = str(payload.get("insight_key", "")).strip()
    if not key or len(key) > 255:
        return _error("A valid insight key is required.")
    dismissed_until = dismiss_insight(user=request.user, insight_key=key)
    return JsonResponse({"ok": True, "dismissed_until": dismissed_until.isoformat()})


@login_required
@require_POST
def record_client_event(request):
    try:
        payload = _parse_json(request)
    except ValidationError as exc:
        return _error(" ".join(exc.messages))
    event_type = payload.get("event_type")
    if event_type != AIEvent.Type.SUGGESTION_USED:
        return _error("That assistant event is not accepted.")
    suggestion_id = str(payload.get("suggestion_id", ""))
    if suggestion_id not in SUGGESTION_LIBRARY:
        return _error("That assistant suggestion is not recognized.")
    record_event(
        user=request.user,
        event_type=AIEvent.Type.SUGGESTION_USED,
        capability=suggestion_id,
        metadata={"suggestion_id": suggestion_id},
    )
    return JsonResponse({"ok": True})


@login_required
@require_POST
def submit_feedback(request):
    try:
        payload = _parse_json(request)
    except ValidationError as exc:
        return _error(" ".join(exc.messages))

    try:
        interaction_id = int(payload.get("interaction_id"))
    except (TypeError, ValueError):
        return _error("A valid interaction is required.")
    rating = str(payload.get("rating", "")).strip()
    category = str(payload.get("category", AIFeedback.Category.ANSWER)).strip()
    comment = str(payload.get("comment", "")).strip()
    if rating not in AIFeedback.Rating.values:
        return _error("Choose helpful or not helpful.")
    if category not in AIFeedback.Category.values:
        return _error("That feedback category is not recognized.")
    if len(comment) > 1000:
        return _error("Keep feedback comments under 1,000 characters.")
    interaction = AIInteraction.objects.filter(
        pk=interaction_id,
        company=request.user.company,
        user=request.user,
    ).first()
    if interaction is None:
        return _error("That assistant interaction was not found.", status=404)
    feedback, _created = AIFeedback.objects.update_or_create(
        interaction=interaction,
        user=request.user,
        defaults={
            "company": request.user.company,
            "rating": rating,
            "category": category,
            "comment": comment,
        },
    )
    record_event(
        user=request.user,
        event_type=AIEvent.Type.FEEDBACK_RECORDED,
        capability="assistant_response",
        interaction=interaction,
        metadata={"rating": rating, "category": category},
    )
    return JsonResponse({"ok": True, "rating": feedback.rating})


@login_required
@require_POST
def report_incident(request):
    try:
        payload = _parse_json(request)
    except ValidationError as exc:
        return _error(" ".join(exc.messages))

    interaction = None
    interaction_id = payload.get("interaction_id")
    if interaction_id not in (None, ""):
        try:
            interaction_id = int(interaction_id)
        except (TypeError, ValueError):
            return _error("A valid interaction is required.")
        interaction = AIInteraction.objects.filter(
            pk=interaction_id,
            company=request.user.company,
            user=request.user,
        ).first()
        if interaction is None:
            return _error("That assistant interaction was not found.", status=404)

    severity = str(payload.get("severity", AIIncident.Severity.MEDIUM)).strip()
    category = str(payload.get("category", AIIncident.Category.OTHER)).strip()
    summary = " ".join(str(payload.get("summary", "")).split())
    details = str(payload.get("details", "")).strip()
    if severity not in AIIncident.Severity.values:
        return _error("That incident severity is not recognized.")
    if category not in AIIncident.Category.values:
        return _error("That incident category is not recognized.")
    if not summary or len(summary) > 500:
        return _error("Enter an incident summary under 500 characters.")
    if len(details) > 5000:
        return _error("Keep incident details under 5,000 characters.")

    incident = AIIncident.objects.create(
        company=request.user.company,
        reported_by=request.user,
        interaction=interaction,
        severity=severity,
        category=category,
        summary=summary,
        details=details,
    )
    policy = get_company_policy(request.user.company)
    if severity == AIIncident.Severity.CRITICAL:
        suspend_company_ai(policy, reason=f"Critical AI incident #{incident.pk}: {summary}")
        policy.refresh_from_db(fields=["suspended_at", "suspension_reason"])
    return JsonResponse(
        {
            "ok": True,
            "incident_id": incident.pk,
            "assistant_suspended": bool(policy.suspended_at),
        }
    )


@login_required
@require_GET
def action_center(request):
    expire_pending_actions(user=request.user)
    pending = AIActionAttempt.objects.filter(
        company=request.user.company,
        user=request.user,
        status=AIActionAttempt.Status.PENDING,
        confirmation_expires_at__gt=timezone.now(),
    ).select_related("interaction").order_by("confirmation_expires_at", "pk")
    recent = (
        AIActionAttempt.objects.filter(
            company=request.user.company,
            user=request.user,
        )
        .exclude(status=AIActionAttempt.Status.PENDING)
        .select_related("interaction")
        .order_by("-created_at", "-pk")[:50]
    )
    return render(
        request,
        "assistant/action_center.html",
        {
            "pending_actions": pending,
            "recent_actions": recent,
        },
    )


@login_required
@require_GET
def pilot_operations(request):
    _require_ai_admin(request.user)
    company = request.user.company
    policy = get_company_policy(company)
    window_start = timezone.now() - timedelta(minutes=policy.failure_window_minutes)
    if policy.failure_count_reset_at and policy.failure_count_reset_at > window_start:
        window_start = policy.failure_count_reset_at
    recent_interaction_failures = AIInteraction.objects.filter(
        company=company,
        status=AIInteraction.Status.FAILED,
        created_at__gte=window_start,
    ).count()
    recent_action_failures = AIActionAttempt.objects.filter(
        company=company,
        status=AIActionAttempt.Status.FAILED,
        created_at__gte=window_start,
    ).count()
    recent_failures = recent_interaction_failures + recent_action_failures
    users = list(company.users.order_by("email"))
    access_by_user = {
        access.user_id: access
        for access in AIUserAccess.objects.filter(company=company, user__in=users)
    }
    user_rows = [
        {
            "user": user,
            "access": access_by_user.get(user.pk),
            "effective_access": (
                policy.access_mode == AICompanySettings.AccessMode.ALL_USERS
                or (
                    policy.access_mode == AICompanySettings.AccessMode.STAFF_ONLY
                    and user.is_staff
                )
                or (
                    policy.access_mode == AICompanySettings.AccessMode.SELECTED_USERS
                    and bool(access_by_user.get(user.pk) and access_by_user[user.pk].enabled)
                )
            ),
        }
        for user in users
    ]
    feedback_summary = AIFeedback.objects.filter(company=company).aggregate(
        total=Count("id"),
        helpful=Count("id", filter=Q(rating=AIFeedback.Rating.HELPFUL)),
        not_helpful=Count("id", filter=Q(rating=AIFeedback.Rating.NOT_HELPFUL)),
    )
    return render(
        request,
        "assistant/pilot_operations.html",
        {
            "policy": policy,
            "recent_failures": recent_failures,
            "user_rows": user_rows,
            "feedback_summary": feedback_summary,
            "recent_feedback": AIFeedback.objects.filter(company=company)
            .select_related("user", "interaction")[:20],
            "open_incidents": AIIncident.objects.filter(
                company=company,
                status=AIIncident.Status.OPEN,
            ).select_related("reported_by", "interaction")[:25],
        },
    )


@login_required
@require_POST
def update_pilot_user_access(request):
    _require_ai_admin(request.user)
    try:
        user_id = int(request.POST.get("user_id", ""))
    except (TypeError, ValueError):
        messages.error(request, "Select a valid company user.")
        return redirect("assistant:pilot-operations")
    company_user = request.user.company.users.filter(pk=user_id).first()
    if company_user is None:
        messages.error(request, "That user does not belong to this company.")
        return redirect("assistant:pilot-operations")
    enabled = request.POST.get("enabled") == "on"
    access, _created = AIUserAccess.objects.update_or_create(
        user=company_user,
        defaults={
            "company": request.user.company,
            "enabled": enabled,
            "granted_by": request.user,
        },
    )
    messages.success(
        request,
        f"AI pilot access {'enabled' if access.enabled else 'disabled'} for {company_user.email}.",
    )
    return redirect("assistant:pilot-operations")


@login_required
@require_POST
def suspend_ai(request):
    _require_ai_admin(request.user)
    policy = get_company_policy(request.user.company)
    reason = " ".join(str(request.POST.get("reason", "Manual pilot pause")).split())[:255]
    changed = suspend_company_ai(policy, reason=reason or "Manual pilot pause")
    if changed:
        record_event(
            user=request.user,
            event_type=AIEvent.Type.CIRCUIT_BREAKER_TRIPPED,
            capability="pilot_safety",
            metadata={"manual": True},
        )
        messages.warning(request, "The AI assistant is suspended for this company.")
    else:
        messages.info(request, "The AI assistant was already suspended.")
    return redirect("assistant:pilot-operations")


@login_required
@require_POST
def resume_ai(request):
    _require_ai_admin(request.user)
    policy = get_company_policy(request.user.company)
    changed = resume_company_ai(policy)
    if changed:
        record_event(
            user=request.user,
            event_type=AIEvent.Type.CIRCUIT_BREAKER_RESET,
            capability="pilot_safety",
            metadata={"manual": True},
        )
        messages.success(request, "The AI assistant is available again for permitted pilot users.")
    else:
        messages.info(request, "The AI assistant was not suspended.")
    return redirect("assistant:pilot-operations")


@login_required
@require_POST
def resolve_incident(request, incident_id):
    _require_ai_admin(request.user)
    incident = AIIncident.objects.filter(
        pk=incident_id,
        company=request.user.company,
    ).first()
    if incident is None:
        raise PermissionDenied("That incident is not available.")
    status = request.POST.get("status", AIIncident.Status.RESOLVED)
    if status not in {AIIncident.Status.RESOLVED, AIIncident.Status.DISMISSED}:
        status = AIIncident.Status.RESOLVED
    incident.status = status
    incident.resolution_note = str(request.POST.get("resolution_note", "")).strip()[:1000]
    incident.resolved_by = request.user
    incident.resolved_at = timezone.now()
    incident.save(
        update_fields=[
            "status",
            "resolution_note",
            "resolved_by",
            "resolved_at",
            "updated_at",
        ]
    )
    messages.success(request, f"Incident #{incident.pk} marked {incident.get_status_display().lower()}.")
    return redirect("assistant:pilot-operations")


@login_required
@require_GET
def readiness(request):
    return render(
        request,
        "assistant/readiness.html",
        {"readiness": build_readiness_report(request.user)},
    )


@login_required
@require_POST
def connection_test(request):
    from .evaluations import run_connection_evaluation

    try:
        run = run_connection_evaluation(user=request.user)
    except (AIPolicyError, AssistantUnavailable, ValidationError) as exc:
        text = " ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        messages.error(request, text)
        return redirect("assistant:readiness")
    except Exception:
        messages.error(
            request,
            "The OpenAI connection test failed safely. Review the recorded evaluation result and deployment logs.",
        )
        return redirect("assistant:readiness")

    if run.status == AIEvaluationRun.Status.PASSED:
        messages.success(request, "OpenAI connection test passed.")
    else:
        messages.error(request, "OpenAI responded, but the connection-test contract did not pass.")
    return redirect("assistant:readiness")


@login_required
@require_GET
def evaluations(request):
    from django.shortcuts import render

    company_runs = (
        AIEvaluationRun.objects.filter(company=request.user.company)
        .select_related("user")
        .prefetch_related("case_results")
        .order_by("-started_at", "-pk")[:25]
    )
    runs = list(company_runs)
    selected_run = None
    requested_run = request.GET.get("run")
    if requested_run:
        selected_run = next((item for item in runs if str(item.pk) == requested_run), None)
    if selected_run is None and runs:
        selected_run = runs[0]
    contract_run = (
        AIEvaluationRun.objects.filter(
            company__isnull=True,
            mode=AIEvaluationRun.Mode.CONTRACT,
        )
        .prefetch_related("case_results")
        .order_by("-started_at", "-pk")
        .first()
    )
    return render(
        request,
        "assistant/evaluations.html",
        {
            "runs": runs,
            "selected_run": selected_run,
            "contract_run": contract_run,
        },
    )


@login_required
@require_GET
def draft_quality(request):
    try:
        days = int(request.GET.get("days", 90))
    except (TypeError, ValueError):
        days = 90
    if days not in {30, 90, 180, 365}:
        days = 90
    return render(
        request,
        "assistant/draft_quality.html",
        {
            "metrics": draft_quality_metrics(request.user, days=days),
            "selected_days": days,
        },
    )


@login_required
@require_GET
def draft_quality_export(request):
    try:
        days = int(request.GET.get("days", 90))
    except (TypeError, ValueError):
        days = 90
    if days not in {30, 90, 180, 365}:
        days = 90
    start = timezone.now() - timedelta(days=days)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="ez360pm-ai-draft-quality-{days}-days.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "created_at",
            "document_type",
            "document_number",
            "tool_name",
            "outcome",
            "revision_count",
            "changed_fields",
            "issued_at",
            "first_delivery_at",
            "deleted_at",
        ]
    )
    reviews = (
        AIDocumentDraftReview.objects.filter(
            company=request.user.company,
            created_at__gte=start,
        )
        .select_related("action_attempt")
        .order_by("created_at", "pk")
    )
    for review in reviews.iterator():
        writer.writerow(
            [
                review.created_at.isoformat(),
                review.document_type,
                _csv_safe(review.document_number),
                review.action_attempt.tool_name,
                review.outcome,
                review.revision_count,
                ";".join(review.changed_fields or []),
                review.issued_at.isoformat() if review.issued_at else "",
                review.first_delivery_at.isoformat() if review.first_delivery_at else "",
                review.deleted_at.isoformat() if review.deleted_at else "",
            ]
        )
    return response


@login_required
@require_GET
def follow_up_evidence(request):
    try:
        days = int(request.GET.get("days", 90))
    except (TypeError, ValueError):
        days = 90
    if days not in {30, 90, 180, 365}:
        days = 90
    return render(
        request,
        "assistant/follow_up_evidence.html",
        {
            "metrics": follow_up_metrics(request.user, days=days),
            "selected_days": days,
        },
    )


@login_required
@require_GET
def follow_up_evidence_export(request):
    try:
        days = int(request.GET.get("days", 90))
    except (TypeError, ValueError):
        days = 90
    if days not in {30, 90, 180, 365}:
        days = 90
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="ez360pm-ai-follow-up-evidence-{days}-days.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "created_at",
            "sent_at",
            "document_type",
            "document_number",
            "client",
            "project",
            "follow_up_kind",
            "recipient_email",
            "delivery_status",
            "subsequent_outcome",
            "hours_to_outcome",
        ]
    )
    for row in follow_up_rows(request.user, days=days, limit=10000):
        delivery = row["delivery"]
        document = row["document"]
        writer.writerow(
            [
                delivery.created_at.isoformat(),
                delivery.sent_at.isoformat() if delivery.sent_at else "",
                document.doc_type,
                _csv_safe(document.number),
                _csv_safe(document.project.client.display_name),
                _csv_safe(f"{document.project.number} — {document.project.name}"),
                delivery.follow_up_kind,
                _csv_safe(delivery.recipient_email),
                delivery.status,
                row["outcome"],
                row["hours_to_outcome"] if row["hours_to_outcome"] is not None else "",
            ]
        )
    return response


@login_required
@require_GET
def usage(request):
    from django.shortcuts import render

    try:
        days = int(request.GET.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    if days not in {7, 30, 90, 365}:
        days = 30
    policy = get_company_policy(request.user.company)
    return render(
        request,
        "assistant/usage.html",
        {
            "metrics": usage_metrics(request.user, days=days, policy=policy),
            "selected_days": days,
            "ai_policy": policy,
        },
    )


class AICompanySettingsView(LoginRequiredMixin, UpdateView):
    form_class = AICompanySettingsForm
    template_name = "assistant/settings.html"

    def get_object(self, queryset=None):
        del queryset
        return get_company_policy(self.request.user.company)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["platform_ai_enabled"] = settings.AI_ASSISTANT_ENABLED
        context["openai_configured"] = bool(settings.OPENAI_API_KEY)
        context["platform_model"] = settings.AI_MODEL
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "AI settings saved.")
        return response

    def get_success_url(self):
        return reverse("assistant:settings")


@login_required
@require_GET
def usage_export(request):
    try:
        days = int(request.GET.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    if days not in {7, 30, 90, 365}:
        days = 30
    start = timezone.now() - timedelta(days=days)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="ez360pm-ai-audit-{days}-days.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "record_type",
            "created_at",
            "user",
            "provider_or_tool",
            "model_or_risk",
            "status",
            "tokens",
            "estimated_cost_usd",
            "latency_ms",
            "error_code",
            "provider_request_ids",
            "client_request_ids",
        ]
    )
    interactions = (
        AIInteraction.objects.filter(
            company=request.user.company,
            created_at__gte=start,
        )
        .select_related("user")
        .order_by("created_at", "pk")
    )
    for item in interactions.iterator():
        writer.writerow(
            [
                "interaction",
                item.created_at.isoformat(),
                item.user.email,
                item.provider,
                item.model,
                item.status,
                item.total_tokens,
                item.estimated_cost_usd,
                item.latency_ms,
                item.error_code,
                "|".join(item.provider_request_ids),
                "|".join(item.provider_client_request_ids),
            ]
        )
    actions = (
        AIActionAttempt.objects.filter(
            company=request.user.company,
            created_at__gte=start,
        )
        .select_related("user")
        .order_by("created_at", "pk")
    )
    for item in actions.iterator():
        writer.writerow(
            [
                "action",
                item.created_at.isoformat(),
                item.user.email,
                item.tool_name,
                item.risk_level,
                item.status,
                "",
                "",
                "",
                item.error_code,
                "",
                "",
            ]
        )
    events = (
        AIEvent.objects.filter(
            company=request.user.company,
            created_at__gte=start,
        )
        .select_related("user")
        .order_by("created_at", "pk")
    )
    for item in events.iterator():
        writer.writerow(
            [
                "event",
                item.created_at.isoformat(),
                item.user.email,
                item.capability,
                item.event_type,
                item.event_type,
                "",
                "",
                "",
                item.metadata.get("error_code", ""),
                "",
                "",
            ]
        )
    feedback = (
        AIFeedback.objects.filter(
            company=request.user.company,
            created_at__gte=start,
        )
        .select_related("user")
        .order_by("created_at", "pk")
    )
    for item in feedback.iterator():
        writer.writerow(
            [
                "feedback",
                item.created_at.isoformat(),
                item.user.email,
                item.category,
                item.rating,
                item.rating,
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )
    incidents = (
        AIIncident.objects.filter(
            company=request.user.company,
            created_at__gte=start,
        )
        .select_related("reported_by")
        .order_by("created_at", "pk")
    )
    for item in incidents.iterator():
        writer.writerow(
            [
                "incident",
                item.created_at.isoformat(),
                item.reported_by.email,
                item.category,
                item.severity,
                item.status,
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )
    return response


@login_required
@require_POST
def confirm_action(request, token):
    policy = get_company_policy(request.user.company)
    try:
        require_assistant_available(policy, user=request.user)
    except AIPolicyError as exc:
        return _error(" ".join(exc.messages), status=503)

    with transaction.atomic():
        attempt = (
            AIActionAttempt.objects.select_for_update()
            .filter(
                confirmation_token=token,
                company=request.user.company,
                user=request.user,
            )
            .first()
        )
        if attempt is None:
            return _error("That assistant action was not found.", status=404)
        if attempt.status == AIActionAttempt.Status.COMPLETED:
            return JsonResponse({"ok": True, **attempt.result, "already_completed": True})
        if attempt.status != AIActionAttempt.Status.PENDING:
            return _error("That assistant action is no longer available.", status=409)
        try:
            require_risk_allowed(policy, attempt.risk_level, user=request.user)
        except AIPolicyError as exc:
            return _error(" ".join(exc.messages), status=403)
        if attempt.confirmation_expires_at <= timezone.now():
            attempt.status = AIActionAttempt.Status.EXPIRED
            attempt.save(update_fields=["status"])
            return _error(
                "That confirmation expired. Ask the assistant to prepare it again.",
                status=409,
            )
        if attempt.risk_level == AIActionAttempt.RiskLevel.EXTERNAL_COMMIT:
            try:
                payload = _parse_json(request)
            except ValidationError as exc:
                return _error(" ".join(exc.messages))
            if payload.get("final_review_acknowledged") is not True:
                return _error(
                    "Review and acknowledge the final recipient, amounts, dates, and action before confirming.",
                    status=409,
                )

        # Commit the one-time confirmation before executing an external action.
        # A concurrent or repeated request will now see CONFIRMED rather than
        # executing the action a second time.
        attempt.status = AIActionAttempt.Status.CONFIRMED
        attempt.confirmed_at = timezone.now()
        attempt.save(update_fields=["status", "confirmed_at"])

    try:
        result = registry.execute_attempt(attempt=attempt, policy=policy)
    except ValidationError as exc:
        record_event(
            user=request.user,
            event_type=AIEvent.Type.TOOL_FAILURE,
            capability=attempt.tool_name,
            interaction=attempt.interaction,
            action_attempt=attempt,
            metadata={"error_code": "domain_validation", "tool_name": attempt.tool_name},
        )
        attempt.status = AIActionAttempt.Status.FAILED
        attempt.error_code = "domain_validation"
        attempt.result = {"message": " ".join(exc.messages)}
        attempt.executed_at = timezone.now()
        attempt.save(update_fields=["status", "error_code", "result", "executed_at"])
        evaluate_failure_circuit_breaker(policy, interaction=attempt.interaction)
        return _error(attempt.result["message"], status=409)
    except Exception:
        record_event(
            user=request.user,
            event_type=AIEvent.Type.TOOL_FAILURE,
            capability=attempt.tool_name,
            interaction=attempt.interaction,
            action_attempt=attempt,
            metadata={"error_code": "execution_error", "tool_name": attempt.tool_name},
        )
        attempt.status = AIActionAttempt.Status.FAILED
        attempt.error_code = "execution_error"
        attempt.result = {
            "message": "The action failed safely. Review the normal EZ360PM screen and try again."
        }
        attempt.executed_at = timezone.now()
        attempt.save(update_fields=["status", "error_code", "result", "executed_at"])
        evaluate_failure_circuit_breaker(policy, interaction=attempt.interaction)
        return _error(attempt.result["message"], status=500)

    # Draft-quality analytics are deliberately best-effort. A successfully
    # created business document must never be reported as failed because the
    # optional metadata tracker encountered a problem.
    try:
        track_completed_draft_action(action_attempt=attempt, result=result)
    except Exception:
        record_event(
            user=request.user,
            event_type=AIEvent.Type.TOOL_FAILURE,
            capability="document_draft_tracking",
            interaction=attempt.interaction,
            action_attempt=attempt,
            metadata={"error_code": "draft_tracking_error", "tool_name": attempt.tool_name},
        )

    public_result = {
        key: value for key, value in result.items() if not str(key).startswith("_")
    }
    attempt.status = AIActionAttempt.Status.COMPLETED
    attempt.result = public_result
    attempt.executed_at = timezone.now()
    attempt.save(update_fields=["status", "result", "executed_at"])
    return JsonResponse({"ok": True, **public_result})


@login_required
@require_POST
@transaction.atomic
def cancel_action(request, token):
    attempt = (
        AIActionAttempt.objects.select_for_update()
        .filter(
            confirmation_token=token,
            company=request.user.company,
            user=request.user,
            status=AIActionAttempt.Status.PENDING,
        )
        .first()
    )
    if attempt is None:
        return _error("That pending assistant action was not found.", status=404)
    try:
        payload = _parse_json(request)
    except ValidationError:
        payload = {}
    reason = payload.get("reason")
    event_type = (
        AIEvent.Type.CORRECTION_REQUESTED
        if reason == "revise"
        else AIEvent.Type.ACTION_CANCELED
    )
    record_event(
        user=request.user,
        event_type=event_type,
        capability=attempt.tool_name,
        interaction=attempt.interaction,
        action_attempt=attempt,
        metadata={"reason": reason or "cancel", "tool_name": attempt.tool_name},
    )
    attempt.status = AIActionAttempt.Status.CANCELED
    attempt.save(update_fields=["status"])
    message = "Assistant action opened for revision." if reason == "revise" else "Assistant action canceled."
    return JsonResponse({"ok": True, "message": message})
