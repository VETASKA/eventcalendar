from django.conf import settings
from django.utils import translation


class AdminLanguageMiddleware:
    """The moderation admin speaks settings.ADMIN_LANGUAGE (Russian). Public pages take the language from the URL
    (LocaleMiddleware + i18n_patterns); the JSON APIs from ?lang=."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/admin/"):
            translation.activate(settings.ADMIN_LANGUAGE)
            request.LANGUAGE_CODE = settings.ADMIN_LANGUAGE
        elif request.path.startswith("/api/"):
            code = (request.GET.get("lang") or "")[:2]
            code = code if code in dict(settings.LANGUAGES) else settings.LANGUAGE_CODE
            translation.activate(code)
            request.LANGUAGE_CODE = code
        return self.get_response(request)
