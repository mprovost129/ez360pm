class RealClientIPMiddleware:
    """Restore the real client IP behind the platform's single reverse-proxy hop.

    Without this, every request's REMOTE_ADDR is the proxy's own address,
    silently breaking per-IP protections: Axes login lockout and the public
    document Stripe checkout rate limiter. Only enabled in production, where
    the app is unreachable except through that trusted proxy.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[-1].strip()
            if client_ip:
                request.META["REMOTE_ADDR"] = client_ip
        return self.get_response(request)
