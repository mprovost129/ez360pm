class PublicDocumentSecurityHeadersMiddleware:
    """Prevent tokenized client documents from leaking through caches or indexes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        match = getattr(request, "resolver_match", None)
        if match and match.namespace == "public-documents":
            response["Cache-Control"] = "private, no-store"
            response["Referrer-Policy"] = "no-referrer"
            response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response
