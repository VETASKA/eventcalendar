from django.conf import settings
from django.utils import translation


class AdminLanguageMiddleware:
    """The moderation admin always speaks settings.ADMIN_LANGUAGE (Russian); public pages are unaffected."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/admin/"):
            translation.activate(settings.ADMIN_LANGUAGE)
            request.LANGUAGE_CODE = settings.ADMIN_LANGUAGE
        return self.get_response(request)
