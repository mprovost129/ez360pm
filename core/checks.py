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
def check_production_email_identity(app_configs, **kwargs):
    if not settings.DEBUG and settings.DEFAULT_FROM_EMAIL == "webmaster@localhost":
        return [
            checks.Warning(
                "DEFAULT_FROM_EMAIL still uses the development default.",
                hint="Set DEFAULT_FROM_EMAIL to the company sending address.",
                id="ez360pm.W001",
            )
        ]
    return []

