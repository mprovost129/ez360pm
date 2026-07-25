from django.http import HttpResponseForbidden


class SuperuserAdministrationMiddleware:
    """Keep Django/JET administration unavailable to ordinary staff accounts."""

    protected_prefixes = ("/admin/", "/jet/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.user.is_authenticated
            and not request.user.is_superuser
            and request.path.startswith(self.protected_prefixes)
        ):
            return HttpResponseForbidden("Administration requires a superuser account.")
        return self.get_response(request)
