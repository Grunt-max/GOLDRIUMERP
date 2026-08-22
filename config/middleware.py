class TailscaleServeSecurityMiddleware:
    """Trust HTTPS metadata only from the local Tailscale Serve reverse proxy."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        remote_addr = request.META.get("REMOTE_ADDR", "")
        tailscale_user = request.META.get("HTTP_TAILSCALE_USER_LOGIN", "")
        if remote_addr in {"127.0.0.1", "::1"} and tailscale_user:
            request.META["wsgi.url_scheme"] = "https"
            request.META["HTTP_X_FORWARDED_PROTO"] = "https"
        return self.get_response(request)
