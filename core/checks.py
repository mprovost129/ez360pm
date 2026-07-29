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
    if not settings.DEBUG and settings.DEFAULT_FROM_EMAIL == "webmaster@localhost":
        issues.append(
            checks.Warning(
                "DEFAULT_FROM_EMAIL still uses the development default.",
                hint="Set DEFAULT_FROM_EMAIL to the company sending address.",
                id="ez360pm.W001",
            )
        )
    if not settings.DEBUG and "localhost" in settings.PUBLIC_BASE_URL:
        issues.append(
            checks.Warning(
                "PUBLIC_BASE_URL still points to localhost.",
                hint="Set PUBLIC_BASE_URL to the public HTTPS application origin.",
                id="ez360pm.W002",
            )
        )
    if not settings.DEBUG and not settings.PUBLIC_BASE_URL.startswith("https://"):
        issues.append(
            checks.Warning(
                "PUBLIC_BASE_URL is not HTTPS.",
                hint="Set PUBLIC_BASE_URL to the public HTTPS application origin.",
                id="ez360pm.W004",
            )
        )
    if not settings.DEBUG and settings.EMAIL_BACKEND.endswith("console.EmailBackend"):
        issues.append(
            checks.Warning(
                "The console email backend is enabled in production.",
                hint="Configure the production SMTP email backend before launch.",
                id="ez360pm.W005",
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
