from django.conf import settings
from django.utils import translation


class AdminLanguageMiddleware:
    """The moderation admin speaks settings.ADMIN_LANGUAGE (Russian). Public pages are Ukrainian until the
    uk / en / pl versions arrive (stage 2), so form errors don't switch language with the browser."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/admin/"):
            translation.activate(settings.ADMIN_LANGUAGE)
            request.LANGUAGE_CODE = settings.ADMIN_LANGUAGE
        else:
            translation.activate(settings.LANGUAGE_CODE)
            request.LANGUAGE_CODE = settings.LANGUAGE_CODE
        return self.get_response(request)
