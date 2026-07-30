from urllib.parse import urlsplit

from django.conf import settings
from django.core import checks


@checks.register(checks.Tags.models)
def check_custom_user_model(app_configs, **kwargs):
    if settings.AUTH_USER_MODEL != "accounts.User":
        return [
            checks.Error(
                "EZ360PM must use accounts.User before the initial migration.",
                id="ez360pm.E001",
            )
        ]
    return []


@checks.register(checks.Tags.security, deploy=True)
def check_runtime_server_configuration(app_configs, **kwargs):
    del app_configs, kwargs
    issues = []
    for message in tuple(getattr(settings, "RUNTIME_CONFIGURATION_ERRORS", ()) or ()):
        issues.append(
            checks.Warning(
                f"Invalid runtime environment setting: {message}",
                hint="EZ360PM is using a safe fallback. Correct the environment value before the next deployment.",
                id="ez360pm.W006",
            )
        )

    timeout = getattr(settings, "GUNICORN_TIMEOUT_SECONDS", 0)
    if timeout < 30:
        issues.append(
            checks.Error(
                "GUNICORN_TIMEOUT_SECONDS must be at least 30 seconds.",
                hint="Use 180 seconds when the AI assistant is enabled, or at least 30 seconds otherwise.",
                id="ez360pm.E002",
            )
        )
    return issues


@checks.register(checks.Tags.security, deploy=True)
def check_production_email_identity(app_configs, **kwargs):
    issues = []
    email_provider = settings.EMAIL_PROVIDER.strip().lower()
    public_base_url = settings.PUBLIC_BASE_URL
    public_url = urlsplit(public_base_url)
    if not settings.DEBUG and settings.DEFAULT_FROM_EMAIL == "webmaster@localhost":
        issues.append(
            checks.Warning(
                "DEFAULT_FROM_EMAIL still uses the development default.",
                hint="Set DEFAULT_FROM_EMAIL to the company sending address.",
                id="ez360pm.W001",
            )
        )
    if not settings.DEBUG and "localhost" in public_base_url:
        issues.append(
            checks.Warning(
                "PUBLIC_BASE_URL still points to localhost.",
                hint="Set PUBLIC_BASE_URL to the public HTTPS application origin.",
                id="ez360pm.W002",
            )
        )
    if not settings.DEBUG and not public_base_url.startswith("https://"):
        issues.append(
            checks.Warning(
                "PUBLIC_BASE_URL is not HTTPS.",
                hint="Set PUBLIC_BASE_URL to the public HTTPS application origin.",
                id="ez360pm.W004",
            )
        )
    if not settings.DEBUG and (
        not public_url.hostname
        or public_url.username
        or public_url.password
        or public_url.path not in {"", "/"}
        or public_url.query
        or public_url.fragment
    ):
        issues.append(
            checks.Error(
                "PUBLIC_BASE_URL must be an origin without credentials, a path, query, or fragment.",
                hint="Use the canonical form https://www.ez360pm.com.",
                id="ez360pm.E003",
            )
        )
    if (
        not settings.DEBUG
        and public_url.hostname
        and not _host_is_allowed(public_url.hostname, settings.ALLOWED_HOSTS)
    ):
        issues.append(
            checks.Error(
                "PUBLIC_BASE_URL is not served by ALLOWED_HOSTS.",
                hint="Add the PUBLIC_BASE_URL hostname to ALLOWED_HOSTS before deployment.",
                id="ez360pm.E004",
            )
        )
    if not settings.DEBUG and settings.EMAIL_BACKEND.endswith("console.EmailBackend"):
        issues.append(
            checks.Warning(
                "The console email backend is enabled in production.",
                hint="Configure the Resend or SMTP production email backend before launch.",
                id="ez360pm.W005",
            )
        )
    if not settings.DEBUG and email_provider not in {"django", "resend"}:
        issues.append(
            checks.Warning(
                "EMAIL_PROVIDER is not recognized.",
                hint="Use 'resend' for production or 'django' for console, test, and SMTP backends.",
                id="ez360pm.W007",
            )
        )
    if not settings.DEBUG and email_provider == "resend":
        if settings.EMAIL_BACKEND != "core.email_backends.ResendEmailBackend":
            issues.append(
                checks.Warning(
                    "Resend is selected but Django is using a different email backend.",
                    hint="Set EMAIL_BACKEND=core.email_backends.ResendEmailBackend so password recovery also uses Resend.",
                    id="ez360pm.W008",
                )
            )
        if not settings.RESEND_API_KEY:
            issues.append(
                checks.Warning(
                    "Resend is selected without an API key.",
                    hint="Set RESEND_API_KEY in the Render environment.",
                    id="ez360pm.W009",
                )
            )
        if not settings.RESEND_WEBHOOK_SECRET:
            issues.append(
                checks.Warning(
                    "Resend delivery webhooks are not configured.",
                    hint="Register /webhooks/resend/ in Resend and set RESEND_WEBHOOK_SECRET.",
                    id="ez360pm.W010",
                )
            )
    stripe_values = (settings.STRIPE_SECRET_KEY, settings.STRIPE_WEBHOOK_SECRET)
    if any(stripe_values) and not all(stripe_values):
        issues.append(
            checks.Warning(
                "Stripe is only partially configured.",
                hint="Set both STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET or neither.",
                id="ez360pm.W003",
            )
        )
    return issues


def _host_is_allowed(hostname, allowed_hosts):
    hostname = hostname.lower().rstrip(".")
    for allowed in allowed_hosts:
        allowed = allowed.lower().rstrip(".")
        if allowed == "*" or allowed == hostname:
            return True
        if allowed.startswith(".") and (
            hostname == allowed[1:] or hostname.endswith(allowed)
        ):
            return True
    return False
