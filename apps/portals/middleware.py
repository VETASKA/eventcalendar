from django.http import HttpResponseNotFound

from .models import Site, SiteDomain

# paths that work on any host (health checks, the Harvey intake API on 127.0.0.1)
HOSTLESS_PREFIXES = ("/healthz", "/api/v1/intake/", "/admin/", "/static/", "/telegram/")


def resolve_site(host: str) -> Site | None:
    host = (host or "").split(":")[0].strip().lower().rstrip(".")
    d = SiteDomain.objects.select_related("site").filter(host=host, site__is_active=True).first()
    if d:
        return d.site
    return Site.objects.filter(is_default=True, is_active=True).first()


class CurrentSiteMiddleware:
    """request.site = the storefront for this Host. Unknown hosts get 404 on public pages."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.site = resolve_site(request.get_host())
        if request.site is None and not request.path.startswith(HOSTLESS_PREFIXES):
            return HttpResponseNotFound("Unknown site")
        return self.get_response(request)
